import * as fs from "fs";
import * as path from "path";
import Parser from "tree-sitter";
import Python from "tree-sitter-python";
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
 * AST Helpers
 * ---------------------------------------------------------
 */

const parser = new Parser();
parser.setLanguage(Python as any);

/**
 * Extracts string values from a Dictionary node
 */
function extractDictKeysFromNode(node: Parser.SyntaxNode): string[] {
  const keys: string[] = [];
  for (const child of node.children) {
    if (child.type === "dictionary_splat") continue;

    if (child.type === "pair") {
      const keyNode = child.childForFieldName("key");
      if (
        keyNode &&
        (keyNode.type === "string" || keyNode.type === "identifier")
      ) {
        keys.push(keyNode.text.replace(/^['"]|['"]$/g, ""));
      }
    }
  }
  return keys;
}

/**
 * Extracts values from a Literal[...] or types from Union[...] node
 */
function extractLiteralValues(node: Parser.SyntaxNode): string[] {
  const values: string[] = [];

  if (node.type !== "subscript" && node.type !== "generic_type") return values;

  let typeName: string | undefined;
  if (node.type === "subscript") {
    typeName = node.childForFieldName("value")?.text;
  } else if (node.type === "generic_type") {
    typeName = node.children.find((c) => c.type === "identifier")?.text;
  }

  // --- Handle Literal[...] ---
  if (typeName === "Literal") {
    const findValues = (n: Parser.SyntaxNode) => {
      if (n.type === "string") {
        // Strip quotes from strings
        values.push(n.text.replace(/^['"]|['"]$/g, ""));
      } else if (
        ["integer", "float", "true", "false", "none"].includes(n.type)
      ) {
        // Capture raw values for primitives (e.g. Literal[1, True, None])
        values.push(n.text);
      }
      for (const child of n.children) {
        findValues(child);
      }
    };
    findValues(node);
  }

  // --- Handle Union[...] ---
  else if (typeName === "Union") {
    for (const child of node.children) {
      // Skip the "Union" keyword itself and punctuation
      if (
        (child.type === "identifier" && child.text === "Union") ||
        ["[", "]", ","].includes(child.type)
      ) {
        continue;
      }

      // Capture Types (bool, str, etc.) and None
      if (
        child.type === "identifier" ||
        child.type === "none" ||
        child.type === "type" ||
        child.type === "primitive_type"
      ) {
        values.push(child.text);
      }
      // Recursively handle nested structures (e.g. Union[str, Literal["a"]])
      else if (child.type === "subscript" || child.type === "generic_type") {
        values.push(...extractLiteralValues(child));
      }
    }
  }

  return values;
}

/**
 * Collects module-level type aliases
 */
function collectTypeAliases(
  rootNode: Parser.SyntaxNode
): Map<string, string[]> {
  const aliases = new Map<string, string[]>();

  for (const child of rootNode.children) {
    if (child.type === "expression_statement") {
      const assignment = child.firstChild;
      if (assignment?.type === "assignment") {
        const left = assignment.childForFieldName("left");
        const right = assignment.childForFieldName("right");

        if (left?.type === "identifier" && right) {
          const values = extractLiteralValues(right);
          if (values.length > 0) {
            aliases.set(left.text, values);
          }
        }
      }
    }
  }
  return aliases;
}

/**
 * ---------------------------------------------------------
 * Core Analysis Logic (AST Based)
 * ---------------------------------------------------------
 */

function analyzeFile(filePath: string, rootDir: string): ComponentMetadata[] {
  const fileContent = fs.readFileSync(filePath, "utf-8");
  const tree = parser.parse(fileContent);
  const components: ComponentMetadata[] = [];
  const typeAliases = collectTypeAliases(tree.rootNode);

  const query = new Parser.Query(
    Python as any,
    `(decorated_definition 
        (decorator) @dec 
        (function_definition) @func
     )`
  );

  const matches = query.matches(tree.rootNode);

  for (const match of matches) {
    const decoratorNode = match.captures.find((c) => c.name === "dec")?.node;
    if (decoratorNode?.text.trim() !== "@component") continue;

    const funcNode = match.captures.find((c) => c.name === "func")?.node;
    if (!funcNode) continue;

    const nameNode = funcNode.childForFieldName("name");
    const componentName = nameNode?.text || "Unknown";
    const paramsNode = funcNode.childForFieldName("parameters");
    const bodyNode = funcNode.childForFieldName("body");

    // 1. Parse Props (Parameters)
    const props: ComponentProp[] = [];
    const propMap = new Map<string, ComponentProp>();
    let acceptsArbitraryProps = false;

    if (paramsNode) {
      for (const param of paramsNode.children) {
        // --- Detect **props (dictionary_splat_pattern) ---
        if (param.type === "dictionary_splat_pattern") {
          acceptsArbitraryProps = true;
          continue;
        }

        // Skip punctuation and list splats (*args)
        if (["(", ")", ",", "list_splat_pattern"].includes(param.type))
          continue;

        let name = "";
        let defaultValue: string | undefined = undefined;
        let typeNode: Parser.SyntaxNode | null = null;

        if (param.type === "identifier") {
          name = param.text;
        } else if (param.type === "default_parameter") {
          name = param.childForFieldName("name")?.text || "";
          defaultValue = param.childForFieldName("value")?.text;
        } else if (param.type === "typed_parameter") {
          const nameNode =
            param.childForFieldName("name") ??
            param.children.find((c) => c.type === "identifier") ??
            null;

          name = nameNode?.text || "";
          typeNode =
            param.childForFieldName("type") ??
            param.children.find(
              (c) => c.type !== "identifier" && c.type !== ":"
            ) ??
            null;
        } else if (param.type === "typed_default_parameter") {
          name = param.childForFieldName("name")?.text || "";
          defaultValue = param.childForFieldName("value")?.text;
          typeNode = param.childForFieldName("type") ?? null;
        }

        // Clean up quotes from default value
        if (defaultValue)
          defaultValue = defaultValue.replace(/^['"]|['"]$/g, "");

        // Exclude standard python args
        if (name === "self" || name === "cls") continue;

        // --- Extract Type String ---
        let propType = "Any";
        if (typeNode) {
          propType = typeNode.text;
        }

        // --- Extract Options ---
        let options: string[] = [];
        if (typeNode) {
          let actualType: Parser.SyntaxNode | null = typeNode;
          if (typeNode.type === "type") {
            actualType = typeNode.firstChild;
          }

          if (actualType?.type === "identifier") {
            options = typeAliases.get(actualType.text) || [];
          } else if (
            actualType?.type === "subscript" ||
            actualType?.type === "generic_type"
          ) {
            options = extractLiteralValues(actualType);
          } else if (actualType) {
            const findSubscript = (
              n: Parser.SyntaxNode
            ): Parser.SyntaxNode | null => {
              if (n.type === "subscript") return n;
              for (const c of n.children) {
                const found = findSubscript(c);
                if (found) return found;
              }
              return null;
            };
            const subscript = findSubscript(actualType);
            if (subscript) {
              options = extractLiteralValues(subscript);
            }
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
    }

    // 2. Parse Body for Dictionaries
    if (bodyNode) {
      for (const statement of bodyNode.children) {
        if (statement.type === "expression_statement") {
          const assignment = statement.firstChild;
          if (assignment?.type === "assignment") {
            const left = assignment.childForFieldName("left");
            const right = assignment.childForFieldName("right");

            if (left?.type === "identifier" && right?.type === "dictionary") {
              const varName = left.text;
              if (varName.endsWith("s")) {
                const propName = varName.slice(0, -1);
                const relatedProp = propMap.get(propName);

                if (relatedProp) {
                  if (!relatedProp.options) {
                    relatedProp.options = extractDictKeysFromNode(right);
                  }
                }
              }
            }
          }
        }
      }
    }

    // Generate Metadata Paths
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
  excludeList: string[] = []
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
      relativeCheck.includes(ex.replace(/^\.\//, ""))
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
  console.log(`🔍 Starting Component Analysis (AST Powered)...`);
  const config = loadConfig();
  let allFiles: string[] = [];

  config.componentScanDirs.forEach((scanDir) => {
    allFiles = walkDirectory(
      path.join(PROJECT_ROOT, scanDir),
      allFiles,
      config.excludeFiles || []
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
