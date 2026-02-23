import * as fs from "fs";
import * as path from "path";
import { parser as pythonParser } from "@lezer/python";
import type { Tree, TreeCursor } from "@lezer/common";
import { getFileMeta } from "./utils";

const { __dirname } = getFileMeta();

/**
 * ---------------------------------------------------------
 * Configuration & Interfaces
 * ---------------------------------------------------------
 */

interface CaspianConfig {
  projectName: string;
  projectRootPath: string;
  componentScanDirs: string[];
  excludeFiles?: string[];
}

interface ComponentProp {
  name: string;
  type: string;
  hasDefault: boolean;
  defaultValue?: string;
  options?: string[];
}

interface ComponentMetadata {
  componentName: string;
  filePath: string;
  relativePath: string;
  importRoute: string;
  acceptsArbitraryProps: boolean;
  props: ComponentProp[];
}

const CONFIG_FILENAME = "caspian.config.json";
const PROJECT_ROOT = path.resolve(__dirname, "..");
const CONFIG_PATH = path.join(PROJECT_ROOT, CONFIG_FILENAME);

/**
 * ---------------------------------------------------------
 * AST Helpers (Lezer)
 * ---------------------------------------------------------
 */

type NodeSpan = {
  name: string;
  from: number;
  to: number;
  children: NodeSpan[];
};

const PY_KEYWORDS = new Set([
  "def",
  "async",
  "class",
  "return",
  "pass",
  "if",
  "elif",
  "else",
  "for",
  "while",
  "try",
  "except",
  "finally",
  "with",
  "lambda",
  "yield",
  "from",
  "import",
  "as",
  "global",
  "nonlocal",
  "assert",
  "raise",
  "del",
  "and",
  "or",
  "not",
  "in",
  "is",
  "True",
  "False",
  "None",
]);

function slice(source: string, node: NodeSpan): string {
  return source.slice(node.from, node.to);
}

function stripQuotes(value: string): string {
  return value.replace(/^['"]|['"]$/g, "");
}

function lower(s: string): string {
  return s.toLowerCase();
}

function isProbablyIdentifierText(text: string): boolean {
  return /^[A-Za-z_][A-Za-z0-9_]*$/.test(text) && !PY_KEYWORDS.has(text);
}

/**
 * Convert Lezer cursor subtree into a plain recursive span tree.
 * This makes traversals simpler and stable for custom heuristics.
 */
function cursorToSpanTree(cursor: TreeCursor): NodeSpan {
  const node: NodeSpan = {
    name: cursor.name,
    from: cursor.from,
    to: cursor.to,
    children: [],
  };

  if (cursor.firstChild()) {
    do {
      node.children.push(cursorToSpanTree(cursor));
    } while (cursor.nextSibling());
    cursor.parent();
  }

  return node;
}

function parsePythonToSpanTree(source: string): { tree: Tree; root: NodeSpan } {
  const tree = pythonParser.parse(source);
  const cursor = tree.cursor();
  const root = cursorToSpanTree(cursor);
  return { tree, root };
}

function walk(
  node: NodeSpan,
  cb: (node: NodeSpan, parent: NodeSpan | null) => void,
  parent: NodeSpan | null = null,
) {
  cb(node, parent);
  for (const child of node.children) walk(child, cb, node);
}

function findFirstDesc(
  node: NodeSpan,
  predicate: (n: NodeSpan) => boolean,
): NodeSpan | null {
  for (const child of node.children) {
    if (predicate(child)) return child;
    const deep = findFirstDesc(child, predicate);
    if (deep) return deep;
  }
  return null;
}

function isFunctionLikeNode(n: NodeSpan, source: string): boolean {
  const name = lower(n.name);
  if (
    !(
      name.includes("function") ||
      name.includes("definition") ||
      name.includes("def")
    )
  ) {
    return false;
  }
  const text = slice(source, n).trimStart();
  return text.startsWith("def ") || text.startsWith("async def ");
}

function isDecoratedLikeNode(n: NodeSpan, source: string): boolean {
  const name = lower(n.name);
  if (name.includes("decorated")) return true;

  // fallback heuristic: node text starts with @ and contains a function definition
  const text = slice(source, n).trimStart();
  return (
    text.startsWith("@") &&
    (text.includes("\ndef ") ||
      text.includes("\nasync def ") ||
      text.includes("def "))
  );
}

function splitTopLevelComma(input: string): string[] {
  const parts: string[] = [];
  let current = "";
  let depthParen = 0;
  let depthBracket = 0;
  let depthBrace = 0;
  let inSingle = false;
  let inDouble = false;
  let escape = false;

  for (let i = 0; i < input.length; i++) {
    const ch = input[i];

    if (escape) {
      current += ch;
      escape = false;
      continue;
    }
    if (ch === "\\") {
      current += ch;
      escape = true;
      continue;
    }

    if (!inDouble && ch === "'" && !inSingle) {
      inSingle = true;
      current += ch;
      continue;
    } else if (inSingle && ch === "'") {
      inSingle = false;
      current += ch;
      continue;
    }

    if (!inSingle && ch === '"' && !inDouble) {
      inDouble = true;
      current += ch;
      continue;
    } else if (inDouble && ch === '"') {
      inDouble = false;
      current += ch;
      continue;
    }

    if (inSingle || inDouble) {
      current += ch;
      continue;
    }

    if (ch === "(") depthParen++;
    else if (ch === ")") depthParen--;
    else if (ch === "[") depthBracket++;
    else if (ch === "]") depthBracket--;
    else if (ch === "{") depthBrace++;
    else if (ch === "}") depthBrace--;

    if (
      ch === "," &&
      depthParen === 0 &&
      depthBracket === 0 &&
      depthBrace === 0
    ) {
      if (current.trim()) parts.push(current.trim());
      current = "";
      continue;
    }

    current += ch;
  }

  if (current.trim()) parts.push(current.trim());
  return parts;
}

/**
 * Extract values from Literal[...] / Union[...] strings.
 * (Leaf text parsing is okay here)
 */
function extractLiteralValuesFromTypeString(typeExpr: string): string[] {
  const expr = typeExpr.trim();
  const values: string[] = [];

  // Literal[...]
  if (expr.startsWith("Literal[") && expr.endsWith("]")) {
    const inner = expr.slice(expr.indexOf("[") + 1, -1);
    for (const part of splitTopLevelComma(inner)) {
      const p = part.trim();
      if (!p) continue;
      if (/^['"].*['"]$/s.test(p)) values.push(stripQuotes(p));
      else values.push(p);
    }
    return values;
  }

  // Union[...]
  if (expr.startsWith("Union[") && expr.endsWith("]")) {
    const inner = expr.slice(expr.indexOf("[") + 1, -1);
    for (const part of splitTopLevelComma(inner)) {
      const p = part.trim();
      if (!p) continue;
      if (p.startsWith("Literal[") && p.endsWith("]")) {
        values.push(...extractLiteralValuesFromTypeString(p));
      } else {
        values.push(p);
      }
    }
    return values;
  }

  return values;
}

/**
 * ---------------------------------------------------------
 * AST-driven Python structure extraction
 * ---------------------------------------------------------
 */

type DecoratedFunctionAst = {
  decoratedNode: NodeSpan;
  functionNode: NodeSpan;
  decoratorNodes: NodeSpan[];
};

function getTopLevelStatements(root: NodeSpan): NodeSpan[] {
  // Lezer root usually has direct statement nodes; keep generic
  return root.children;
}

/**
 * Find decorated functions by AST traversal (no regex structure scan)
 */
function findDecoratedFunctionsAst(
  root: NodeSpan,
  source: string,
): DecoratedFunctionAst[] {
  const results: DecoratedFunctionAst[] = [];

  walk(root, (node) => {
    if (!isDecoratedLikeNode(node, source)) return;

    const functionNode =
      node.children.find((c) => isFunctionLikeNode(c, source)) ||
      findFirstDesc(node, (c) => isFunctionLikeNode(c, source));

    if (!functionNode) return;

    // Decorators are usually sibling children before function node
    const decoratorNodes = node.children.filter((c) => {
      if (c === functionNode) return false;
      const txt = slice(source, c).trimStart();
      return txt.startsWith("@");
    });

    results.push({
      decoratedNode: node,
      functionNode,
      decoratorNodes,
    });
  });

  return results;
}

function decoratorMatchesComponent(node: NodeSpan, source: string): boolean {
  const txt = slice(source, node).trim();
  // Supports @component and @component(...)
  return txt === "@component" || txt.startsWith("@component(");
}

function extractFunctionNameAst(
  functionNode: NodeSpan,
  source: string,
): string {
  const txt = slice(source, functionNode);

  // Header-based extraction (robust fix for "def" bug)
  // Supports:
  //   def Profile(...)
  //   async def Profile(...)
  const parenIndex = txt.indexOf("(");
  if (parenIndex > 0) {
    const header = txt.slice(0, parenIndex);
    const defIndex = header.indexOf("def");

    if (defIndex >= 0) {
      const afterDef = header.slice(defIndex + 3).trim();

      let i = 0;
      while (i < afterDef.length && /\s/.test(afterDef[i])) i++;

      let j = i;
      while (j < afterDef.length && /[A-Za-z0-9_]/.test(afterDef[j])) j++;

      const candidate = afterDef.slice(i, j).trim();
      if (candidate && isProbablyIdentifierText(candidate)) {
        return candidate;
      }
    }
  }

  // AST fallback: direct children identifiers excluding keywords
  for (const child of functionNode.children) {
    const t = slice(source, child).trim();
    if (isProbablyIdentifierText(t)) return t;
  }

  // Deep fallback
  const nameNode = findFirstDesc(functionNode, (n) => {
    const t = slice(source, n).trim();
    return isProbablyIdentifierText(t);
  });
  if (nameNode) return slice(source, nameNode).trim();

  return "Unknown";
}

function findParamListNode(
  functionNode: NodeSpan,
  source: string,
): NodeSpan | null {
  // Prefer child whose text starts with "(" and ends with ")"
  for (const child of functionNode.children) {
    const txt = slice(source, child).trim();
    if (txt.startsWith("(") && txt.endsWith(")")) return child;
  }

  // fallback deep search
  return findFirstDesc(functionNode, (n) => {
    const txt = slice(source, n).trim();
    return txt.startsWith("(") && txt.endsWith(")");
  });
}

function extractParamListTextAst(
  functionNode: NodeSpan,
  source: string,
): string {
  const paramsNode = findParamListNode(functionNode, source);
  if (!paramsNode) return "";

  const txt = slice(source, paramsNode).trim();
  if (txt.startsWith("(") && txt.endsWith(")")) {
    return txt.slice(1, -1);
  }
  return txt;
}

function findFunctionBodyNode(
  functionNode: NodeSpan,
  source: string,
): NodeSpan | null {
  // Heuristic: child block after ":" with multiline content often is the body
  const candidates = functionNode.children.filter((c) => {
    const txt = slice(source, c);
    return (
      txt.includes("\n") ||
      txt.trimStart().startsWith("return") ||
      txt.trimStart().startsWith("pass")
    );
  });

  if (candidates.length > 0) {
    // last candidate tends to be body
    return candidates[candidates.length - 1];
  }

  // fallback deep search for a block/suite-like name
  return findFirstDesc(functionNode, (n) => {
    const name = lower(n.name);
    return (
      name.includes("body") || name.includes("suite") || name.includes("block")
    );
  });
}

function extractFunctionBodyTextAst(
  functionNode: NodeSpan,
  source: string,
): string {
  const bodyNode = findFunctionBodyNode(functionNode, source);
  if (!bodyNode) {
    // fallback: slice after first colon in function text
    const txt = slice(source, functionNode);
    const idx = txt.indexOf(":");
    return idx >= 0 ? txt.slice(idx + 1) : "";
  }
  return slice(source, bodyNode);
}

/**
 * Parse a single parameter chunk (still text-level, but only for leaf content)
 */
function parseParameterChunk(raw: string): {
  name: string;
  type?: string;
  defaultValue?: string;
  arbitraryDict?: boolean;
  listSplat?: boolean;
} | null {
  let s = raw.trim();
  if (!s) return null;

  // Positional-only / keyword-only separators
  if (s === "/" || s === "*") return null;

  // **kwargs
  if (s.startsWith("**")) {
    return { name: s.slice(2).trim(), arbitraryDict: true };
  }

  // *args
  if (s.startsWith("*")) {
    return { name: s.slice(1).trim(), listSplat: true };
  }

  // Split default at top-level "="
  let left = s;
  let defaultValue: string | undefined;

  {
    let depthParen = 0,
      depthBracket = 0,
      depthBrace = 0;
    let inSingle = false,
      inDouble = false,
      escape = false;
    let eqIndex = -1;

    for (let i = 0; i < s.length; i++) {
      const ch = s[i];

      if (escape) {
        escape = false;
        continue;
      }
      if (ch === "\\") {
        escape = true;
        continue;
      }

      if (!inDouble && ch === "'" && !inSingle) {
        inSingle = true;
        continue;
      } else if (inSingle && ch === "'") {
        inSingle = false;
        continue;
      }

      if (!inSingle && ch === '"' && !inDouble) {
        inDouble = true;
        continue;
      } else if (inDouble && ch === '"') {
        inDouble = false;
        continue;
      }

      if (inSingle || inDouble) continue;

      if (ch === "(") depthParen++;
      else if (ch === ")") depthParen--;
      else if (ch === "[") depthBracket++;
      else if (ch === "]") depthBracket--;
      else if (ch === "{") depthBrace++;
      else if (ch === "}") depthBrace--;

      if (
        ch === "=" &&
        depthParen === 0 &&
        depthBracket === 0 &&
        depthBrace === 0
      ) {
        eqIndex = i;
        break;
      }
    }

    if (eqIndex >= 0) {
      left = s.slice(0, eqIndex).trim();
      defaultValue = s.slice(eqIndex + 1).trim();
    }
  }

  // Split type annotation at top-level ":"
  let name = left;
  let type: string | undefined;

  {
    let depthParen = 0,
      depthBracket = 0,
      depthBrace = 0;
    let inSingle = false,
      inDouble = false,
      escape = false;
    let colonIndex = -1;

    for (let i = 0; i < left.length; i++) {
      const ch = left[i];

      if (escape) {
        escape = false;
        continue;
      }
      if (ch === "\\") {
        escape = true;
        continue;
      }

      if (!inDouble && ch === "'" && !inSingle) {
        inSingle = true;
        continue;
      } else if (inSingle && ch === "'") {
        inSingle = false;
        continue;
      }

      if (!inSingle && ch === '"' && !inDouble) {
        inDouble = true;
        continue;
      } else if (inDouble && ch === '"') {
        inDouble = false;
        continue;
      }

      if (inSingle || inDouble) continue;

      if (ch === "(") depthParen++;
      else if (ch === ")") depthParen--;
      else if (ch === "[") depthBracket++;
      else if (ch === "]") depthBracket--;
      else if (ch === "{") depthBrace++;
      else if (ch === "}") depthBrace--;

      if (
        ch === ":" &&
        depthParen === 0 &&
        depthBracket === 0 &&
        depthBrace === 0
      ) {
        colonIndex = i;
        break;
      }
    }

    if (colonIndex >= 0) {
      name = left.slice(0, colonIndex).trim();
      type = left.slice(colonIndex + 1).trim();
    }
  }

  if (!name) return null;
  return { name, type, defaultValue };
}

/**
 * AST-based top-level alias collection:
 *   Size = Literal["sm","md"]
 *   Foo = Union[str, Literal["x"]]
 */
function collectTypeAliasesAst(
  root: NodeSpan,
  source: string,
): Map<string, string[]> {
  const aliases = new Map<string, string[]>();

  for (const stmt of getTopLevelStatements(root)) {
    const stmtText = slice(source, stmt).trim();
    if (!stmtText || stmtText.startsWith("@")) continue;

    // structure is AST (top-level statement); leaf extraction uses text
    const eqIndex = stmtText.indexOf("=");
    if (eqIndex < 0) continue;

    const left = stmtText.slice(0, eqIndex).trim();
    const right = stmtText.slice(eqIndex + 1).trim();

    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(left)) continue;

    const values = extractLiteralValuesFromTypeString(right);
    if (values.length > 0) {
      aliases.set(left, values);
    }
  }

  return aliases;
}

/**
 * Dictionary key extraction from dict literal text (token-aware, no regex)
 */
function extractDictKeysFromText(dictText: string): string[] {
  const keys: string[] = [];

  const inner = dictText.trim();
  if (!(inner.startsWith("{") && inner.endsWith("}"))) return keys;

  const body = inner.slice(1, -1);
  const pairs = splitTopLevelComma(body);

  for (const part of pairs) {
    const p = part.trim();
    if (!p || p.startsWith("**")) continue;

    // split top-level colon
    let colonIndex = -1;
    let depthParen = 0,
      depthBracket = 0,
      depthBrace = 0;
    let inSingle = false,
      inDouble = false,
      escape = false;

    for (let i = 0; i < p.length; i++) {
      const ch = p[i];
      if (escape) {
        escape = false;
        continue;
      }
      if (ch === "\\") {
        escape = true;
        continue;
      }

      if (!inDouble && ch === "'" && !inSingle) {
        inSingle = true;
        continue;
      } else if (inSingle && ch === "'") {
        inSingle = false;
        continue;
      }

      if (!inSingle && ch === '"' && !inDouble) {
        inDouble = true;
        continue;
      } else if (inDouble && ch === '"') {
        inDouble = false;
        continue;
      }

      if (inSingle || inDouble) continue;

      if (ch === "(") depthParen++;
      else if (ch === ")") depthParen--;
      else if (ch === "[") depthBracket++;
      else if (ch === "]") depthBracket--;
      else if (ch === "{") depthBrace++;
      else if (ch === "}") depthBrace--;

      if (
        ch === ":" &&
        depthParen === 0 &&
        depthBracket === 0 &&
        depthBrace === 0
      ) {
        colonIndex = i;
        break;
      }
    }

    if (colonIndex < 0) continue;
    const keyExpr = p.slice(0, colonIndex).trim();

    if (/^['"].*['"]$/s.test(keyExpr)) {
      keys.push(stripQuotes(keyExpr));
    } else if (/^[A-Za-z_][A-Za-z0-9_]*$/.test(keyExpr)) {
      keys.push(keyExpr);
    }
  }

  return [...new Set(keys)];
}

/**
 * AST-ish body dictionary assignments:
 * scoped body parsing (less fragile than whole-file regex)
 */
function extractBodyDictAssignmentsAst(
  bodyText: string,
): Map<string, string[]> {
  const out = new Map<string, string[]>();
  const lines = bodyText.split(/\r?\n/);

  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed || trimmed.startsWith("#")) {
      i++;
      continue;
    }

    // Look for `name = {`
    const eq = line.indexOf("=");
    if (eq < 0) {
      i++;
      continue;
    }

    const left = line.slice(0, eq).trim();
    const rightStart = line.slice(eq + 1).trimStart();

    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(left) || !rightStart.startsWith("{")) {
      i++;
      continue;
    }

    // collect balanced dict literal across lines
    let dictText = line.slice(line.indexOf("{"));
    let depth = 0;
    let started = false;
    let done = false;

    const countBraces = (s: string) => {
      let inSingle = false;
      let inDouble = false;
      let escape = false;

      for (const ch of s) {
        if (escape) {
          escape = false;
          continue;
        }
        if (ch === "\\") {
          escape = true;
          continue;
        }

        if (!inDouble && ch === "'" && !inSingle) {
          inSingle = true;
          continue;
        } else if (inSingle && ch === "'") {
          inSingle = false;
          continue;
        }

        if (!inSingle && ch === '"' && !inDouble) {
          inDouble = true;
          continue;
        } else if (inDouble && ch === '"') {
          inDouble = false;
          continue;
        }

        if (inSingle || inDouble) continue;

        if (ch === "{") {
          depth++;
          started = true;
        } else if (ch === "}") {
          depth--;
          if (started && depth === 0) done = true;
        }
      }
    };

    countBraces(dictText);

    let j = i + 1;
    while (!done && j < lines.length) {
      dictText += "\n" + lines[j];
      countBraces(lines[j]);
      j++;
    }

    if (done) {
      out.set(left, extractDictKeysFromText(dictText));
      i = j;
      continue;
    }

    i++;
  }

  return out;
}

/**
 * ---------------------------------------------------------
 * Core Analysis Logic (AST-first)
 * ---------------------------------------------------------
 */

function analyzeFile(filePath: string, rootDir: string): ComponentMetadata[] {
  const fileContent = fs.readFileSync(filePath, "utf-8");
  const { root } = parsePythonToSpanTree(fileContent);

  const components: ComponentMetadata[] = [];
  const typeAliases = collectTypeAliasesAst(root, fileContent);
  const decoratedFns = findDecoratedFunctionsAst(root, fileContent);

  for (const item of decoratedFns) {
    const hasComponentDecorator = item.decoratorNodes.some((d) =>
      decoratorMatchesComponent(d, fileContent),
    );

    // fallback for grammars that don't expose decorator children cleanly
    const decoratedText = slice(fileContent, item.decoratedNode);
    const fallbackHasComponent =
      decoratedText.trimStart().startsWith("@component") ||
      decoratedText.includes("\n@component");

    if (!hasComponentDecorator && !fallbackHasComponent) continue;

    const componentName = extractFunctionNameAst(
      item.functionNode,
      fileContent,
    );
    const paramsText = extractParamListTextAst(item.functionNode, fileContent);
    const bodyText = extractFunctionBodyTextAst(item.functionNode, fileContent);

    // 1) Parse Props (parameters)
    const props: ComponentProp[] = [];
    const propMap = new Map<string, ComponentProp>();
    let acceptsArbitraryProps = false;

    for (const rawParam of splitTopLevelComma(paramsText)) {
      const parsed = parseParameterChunk(rawParam);
      if (!parsed) continue;

      if (parsed.arbitraryDict) {
        acceptsArbitraryProps = true;
        continue;
      }
      if (parsed.listSplat) {
        continue; // skip *args
      }

      let { name, type, defaultValue } = parsed;

      if (name === "self" || name === "cls") continue;

      if (defaultValue && /^['"].*['"]$/s.test(defaultValue)) {
        defaultValue = stripQuotes(defaultValue);
      }

      const propType = type?.trim() || "Any";

      let options: string[] = [];
      if (type) {
        const t = type.trim();
        if (/^[A-Za-z_][A-Za-z0-9_]*$/.test(t)) {
          options = typeAliases.get(t) || [];
        } else {
          options = extractLiteralValuesFromTypeString(t);
        }
      }

      const propObj: ComponentProp = {
        name,
        type: propType,
        hasDefault: defaultValue !== undefined,
        defaultValue,
        options: options.length > 0 ? options : undefined,
      };

      props.push(propObj);
      propMap.set(name, propObj);
    }

    // 2) Infer options from body dict assignments
    const dictAssignments = extractBodyDictAssignmentsAst(bodyText);

    for (const [varName, keys] of dictAssignments.entries()) {
      if (!varName.endsWith("s")) continue;
      const propName = varName.slice(0, -1);
      const relatedProp = propMap.get(propName);
      if (relatedProp && !relatedProp.options && keys.length > 0) {
        relatedProp.options = keys;
      }
    }

    // 3) Paths
    const relativePath = path.relative(rootDir, filePath).replace(/\\/g, "/");
    const pathNoExt = relativePath.replace(/\.py$/, "");
    const importRoute = pathNoExt.replace(/\//g, ".");

    components.push({
      componentName,
      filePath,
      relativePath,
      importRoute,
      acceptsArbitraryProps,
      props,
    });
  }

  return components;
}

/**
 * ---------------------------------------------------------
 * File System Helpers
 * ---------------------------------------------------------
 */

function loadConfig(): CaspianConfig {
  if (!fs.existsSync(CONFIG_PATH)) {
    console.error(`❌ Configuration file not found at: ${CONFIG_PATH}`);
    process.exit(1);
  }
  return JSON.parse(fs.readFileSync(CONFIG_PATH, "utf-8"));
}

function walkDirectory(
  dir: string,
  fileList: string[] = [],
  excludeList: string[] = [],
): string[] {
  if (!fs.existsSync(dir)) return fileList;
  const files = fs.readdirSync(dir);

  files.forEach((file) => {
    const fullPath = path.join(dir, file);
    const stat = fs.statSync(fullPath);
    const relativeCheck = path
      .relative(PROJECT_ROOT, fullPath)
      .replace(/\\/g, "/");

    const isExcluded = excludeList.some((ex) =>
      relativeCheck.includes(ex.replace(/^\.\//, "")),
    );
    if (isExcluded) return;

    if (stat.isDirectory()) {
      walkDirectory(fullPath, fileList, excludeList);
    } else if (path.extname(file) === ".py") {
      fileList.push(fullPath);
    }
  });

  return fileList;
}

/**
 * ---------------------------------------------------------
 * Execution Entry Point
 * ---------------------------------------------------------
 */

export async function componentMap() {
  console.log(`🔍 Starting Component Analysis (Lezer AST-first)...`);
  const config = loadConfig();
  let allFiles: string[] = [];

  config.componentScanDirs.forEach((scanDir) => {
    allFiles = walkDirectory(
      path.join(PROJECT_ROOT, scanDir),
      allFiles,
      config.excludeFiles || [],
    );
  });

  console.log(`📂 Found ${allFiles.length} Python files.`);
  const componentRegistry: ComponentMetadata[] = [];

  allFiles.forEach((file) => {
    try {
      const foundComponents = analyzeFile(file, PROJECT_ROOT);
      componentRegistry.push(...foundComponents);
    } catch (e) {
      console.warn(`⚠️ Failed to parse ${file}:`, e);
    }
  });

  console.log(`✅ Discovered ${componentRegistry.length} Components.`);

  const outputPath = path.join(__dirname, "component-map.json");
  if (componentRegistry.length > 0 || !fs.existsSync(outputPath)) {
    fs.writeFileSync(outputPath, JSON.stringify(componentRegistry, null, 2));
    console.log(`📝 Component map written to: ${outputPath}`);
  }
}
