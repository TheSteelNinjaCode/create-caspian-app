import { Plugin } from "vite";
import path from "path";
import { writeFileSync, mkdirSync, existsSync, readFileSync } from "fs";

/**
 * Generates `.casp/global-functions.d.ts` so editors can type the globals
 * registered via `createGlobalSingleton("name", value)` in `ts/main.ts`.
 *
 * This intentionally does NOT use the TypeScript Compiler API. The project runs
 * the native (Go-based) `typescript` package (v7+), whose npm entry only exposes
 * `version`/`versionMajorMinor` — the classic API (`ts.createSourceFile`,
 * `createProgram`, the type checker, `ScriptTarget`, …) is gone. Instead we
 * parse the small, first-party `ts/main.ts` directly and emit each global as a
 * `typeof import("...")` type, which is fully type-accurate and needs no checker.
 */
export function generateGlobalTypes(): Plugin {
  const dtsPath = path.resolve(process.cwd(), ".casp", "global-functions.d.ts");

  return {
    name: "generate-global-types",

    buildStart() {
      const mainPath = path.resolve(process.cwd(), "ts", "main.ts");

      if (!existsSync(mainPath)) {
        console.warn("⚠️  ts/main.ts not found, skipping type generation");
        return;
      }

      const content = readFileSync(mainPath, "utf-8");
      const globals = parseGlobalSingletons(content);

      if (globals.length === 0) {
        console.warn("⚠️  No createGlobalSingleton calls found");
        return;
      }

      generateDts(globals, dtsPath, mainPath);
    },
  };
}

interface GlobalDeclaration {
  name: string;
  importPath: string;
  exportName: string;
  isNamespace: boolean;
}

interface ImportInfo {
  path: string;
  originalName: string;
  isNamespace: boolean;
}

/** Strip line and block comments so they can't confuse the statement scans. */
function stripComments(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/[^\n]*/g, "$1");
}

/**
 * Build a map of local binding name -> import info for a module's imports.
 * Handles `import { a, b as c } from "x"`, `import * as ns from "x"`, and
 * `import def from "x"`.
 */
function parseImports(source: string): Map<string, ImportInfo> {
  const importMap = new Map<string, ImportInfo>();
  const importRe = /import\s+([\s\S]*?)\s+from\s+["']([^"']+)["']/g;

  let match: RegExpExecArray | null;
  while ((match = importRe.exec(source)) !== null) {
    const clause = match[1].trim();
    const modulePath = match[2];

    // Namespace import: * as ns
    const nsMatch = clause.match(/^\*\s+as\s+([A-Za-z_$][\w$]*)$/);
    if (nsMatch) {
      importMap.set(nsMatch[1], {
        path: modulePath,
        originalName: nsMatch[1],
        isNamespace: true,
      });
      continue;
    }

    // Split into a possible default binding and a named-bindings block.
    const namedMatch = clause.match(/\{([\s\S]*)\}/);
    const defaultPart = clause
      .replace(/\{[\s\S]*\}/, "")
      .replace(/,/g, "")
      .trim();

    if (defaultPart) {
      importMap.set(defaultPart, {
        path: modulePath,
        originalName: "default",
        isNamespace: false,
      });
    }

    if (namedMatch) {
      for (const rawSpec of namedMatch[1].split(",")) {
        const spec = rawSpec.trim();
        if (!spec) continue;
        const asMatch = spec.match(
          /^([A-Za-z_$][\w$]*)\s+as\s+([A-Za-z_$][\w$]*)$/,
        );
        if (asMatch) {
          importMap.set(asMatch[2], {
            path: modulePath,
            originalName: asMatch[1],
            isNamespace: false,
          });
        } else if (/^[A-Za-z_$][\w$]*$/.test(spec)) {
          importMap.set(spec, {
            path: modulePath,
            originalName: spec,
            isNamespace: false,
          });
        }
      }
    }
  }

  return importMap;
}

function parseGlobalSingletons(rawSource: string): GlobalDeclaration[] {
  const source = stripComments(rawSource);
  const importMap = parseImports(source);

  const globals: GlobalDeclaration[] = [];
  const callRe =
    /createGlobalSingleton\s*\(\s*["']([^"']+)["']\s*,\s*([A-Za-z_$][\w$]*)\s*[),]/g;

  let match: RegExpExecArray | null;
  while ((match = callRe.exec(source)) !== null) {
    const name = match[1];
    const variable = match[2];
    const importInfo = importMap.get(variable);
    if (importInfo) {
      globals.push({
        name,
        importPath: importInfo.path,
        exportName: importInfo.originalName,
        isNamespace: importInfo.isNamespace,
      });
    }
  }

  return globals;
}

/**
 * Rewrite an import path so it resolves from the generated `.d.ts` location.
 * `ts/main.ts` imports are relative to `ts/`, but the declaration file lives in
 * `.casp/`, so a bare `./x.js` must become `../ts/x.js`. Bare module specifiers
 * (npm packages) are returned unchanged.
 */
function toDtsRelativeImport(
  importPath: string,
  mainPath: string,
  dtsPath: string,
): string {
  const isBareModule =
    !importPath.startsWith(".") && !importPath.startsWith("/");
  if (isBareModule) return importPath;

  const abs = path.resolve(path.dirname(mainPath), importPath);
  let rel = path.relative(path.dirname(dtsPath), abs).split(path.sep).join("/");
  if (!rel.startsWith(".")) rel = `./${rel}`;
  return rel;
}

function signatureFor(
  global: GlobalDeclaration,
  mainPath: string,
  dtsPath: string,
): string {
  const spec = toDtsRelativeImport(global.importPath, mainPath, dtsPath);
  if (global.isNamespace) return `typeof import("${spec}")`;
  if (global.exportName === "default")
    return `typeof import("${spec}").default`;
  return `typeof import("${spec}").${global.exportName}`;
}

function generateDts(
  globals: GlobalDeclaration[],
  dtsPath: string,
  mainPath: string,
) {
  const declarations = globals
    .map((global) => {
      const sig = signatureFor(global, mainPath, dtsPath);
      // Inject the original source path as a comment for the editor extension.
      return `  // @source: ${global.importPath}\n  const ${global.name}: ${sig};`;
    })
    .join("\n");

  const windowDeclarations = globals
    .map(({ name }) => `    ${name}: typeof globalThis.${name};`)
    .join("\n");

  const content = `// Auto-generated by Vite plugin
// Do not edit manually - regenerate with: npm run dev or npm run build
// Source: ts/main.ts

declare global {
${declarations}

  interface Window {
${windowDeclarations}
  }
}

export {};
`;

  const dir = path.dirname(dtsPath);
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
  writeFileSync(dtsPath, content, "utf-8");
  console.log(`✅ Generated ${path.relative(process.cwd(), dtsPath)}`);
}
