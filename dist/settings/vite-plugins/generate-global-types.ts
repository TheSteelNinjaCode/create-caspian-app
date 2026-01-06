import { Plugin } from "vite";
import path from "path";
import { writeFileSync, mkdirSync, existsSync, readFileSync } from "fs";
import ts from "typescript";

export function generateGlobalTypes(): Plugin {
  const dtsPath = path.resolve(process.cwd(), ".pp", "global-functions.d.ts");

  return {
    name: "generate-global-types",

    buildStart() {
      const mainPath = path.resolve(process.cwd(), "ts", "main.ts");

      if (!existsSync(mainPath)) {
        console.warn("⚠️  ts/main.ts not found, skipping type generation");
        return;
      }

      const content = readFileSync(mainPath, "utf-8");
      const globals = parseGlobalSingletons(content, mainPath);

      if (globals.length === 0) {
        console.warn("⚠️  No createGlobalSingleton calls found");
        return;
      }

      generateDtsWithTypeChecker(globals, dtsPath, mainPath);
    },
  };
}
interface GlobalDeclaration {
  name: string;
  importPath: string;
  exportName: string;
}

function parseGlobalSingletons(
  content: string,
  filePath: string
): GlobalDeclaration[] {
  const sf = ts.createSourceFile(
    filePath,
    content,
    ts.ScriptTarget.Latest,
    true
  );

  const globals: GlobalDeclaration[] = [];
  const importMap = new Map<string, { path: string; originalName: string }>();

  sf.statements.forEach((stmt) => {
    if (ts.isImportDeclaration(stmt) && stmt.importClause) {
      const moduleSpecifier = (stmt.moduleSpecifier as ts.StringLiteral).text;

      if (stmt.importClause.namedBindings) {
        if (ts.isNamedImports(stmt.importClause.namedBindings)) {
          stmt.importClause.namedBindings.elements.forEach((element) => {
            const localName = element.name.text;
            const importedName = element.propertyName
              ? element.propertyName.text
              : localName;

            importMap.set(localName, {
              path: moduleSpecifier,
              originalName: importedName,
            });
          });
        }
      }
    }
  });

  function visit(node: ts.Node) {
    if (
      ts.isCallExpression(node) &&
      ts.isIdentifier(node.expression) &&
      node.expression.text === "createGlobalSingleton"
    ) {
      if (node.arguments.length >= 2) {
        const nameArg = node.arguments[0];
        const valueArg = node.arguments[1];

        if (ts.isStringLiteral(nameArg) && ts.isIdentifier(valueArg)) {
          const name = nameArg.text;
          const variable = valueArg.text;
          const importInfo = importMap.get(variable);

          if (importInfo) {
            globals.push({
              name,
              importPath: importInfo.path,
              exportName: importInfo.originalName,
            });
          }
        }
      }
    }

    ts.forEachChild(node, visit);
  }

  visit(sf);
  return globals;
}

function generateDtsWithTypeChecker(
  globals: GlobalDeclaration[],
  dtsPath: string,
  mainPath: string
) {
  const configPath = ts.findConfigFile(
    process.cwd(),
    ts.sys.fileExists,
    "tsconfig.json"
  );

  const { config } = configPath
    ? ts.readConfigFile(configPath, ts.sys.readFile)
    : { config: {} };

  const { options } = ts.parseJsonConfigFileContent(
    config,
    ts.sys,
    process.cwd()
  );

  const program = ts.createProgram([mainPath], options);
  const checker = program.getTypeChecker();
  const sourceFile = program.getSourceFile(mainPath);

  if (!sourceFile) {
    console.warn("⚠️  Could not load main.ts for type checking");
    generateFallbackDts(globals, dtsPath);
    return;
  }

  const signatures = new Map<string, string>();

  const importMap = new Map<string, ts.ImportDeclaration>();
  sourceFile.statements.forEach((stmt) => {
    if (ts.isImportDeclaration(stmt) && stmt.importClause?.namedBindings) {
      if (ts.isNamedImports(stmt.importClause.namedBindings)) {
        stmt.importClause.namedBindings.elements.forEach((element) => {
          importMap.set(element.name.text, stmt);
        });
      }
    }
  });

  globals.forEach(({ name, exportName }) => {
    try {
      const importDecl = importMap.get(exportName);
      if (!importDecl || !importDecl.importClause?.namedBindings) {
        signatures.set(name, "(...args: any[]) => any");
        return;
      }

      if (ts.isNamedImports(importDecl.importClause.namedBindings)) {
        const importSpec = importDecl.importClause.namedBindings.elements.find(
          (el) => el.name.text === exportName
        );

        if (importSpec) {
          const symbol = checker.getSymbolAtLocation(importSpec.name);
          if (symbol) {
            const type = checker.getTypeOfSymbolAtLocation(
              symbol,
              importSpec.name
            );
            const signature = checker.typeToString(
              type,
              undefined,
              ts.TypeFormatFlags.NoTruncation
            );
            signatures.set(name, signature);
            return;
          }
        }
      }

      signatures.set(name, "(...args: any[]) => any");
    } catch (error) {
      console.warn(`⚠️  Failed to extract type for ${name}:`, error);
      signatures.set(name, "(...args: any[]) => any");
    }
  });

  const declarations = globals
    .map(({ name }) => {
      const sig = signatures.get(name) || "(...args: any[]) => any";
      return `  const ${name}: ${sig};`;
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
  if (!existsSync(dir)) {
    mkdirSync(dir, { recursive: true });
  }

  writeFileSync(dtsPath, content, "utf-8");
  console.log(`✅ Generated ${path.relative(process.cwd(), dtsPath)}`);
}

function generateFallbackDts(globals: GlobalDeclaration[], dtsPath: string) {
  const declarations = globals
    .map(({ name }) => `  const ${name}: (...args: any[]) => any;`)
    .join("\n");

  const windowDeclarations = globals
    .map(({ name }) => `    ${name}: typeof globalThis.${name};`)
    .join("\n");

  const content = `// Auto-generated by Vite plugin
declare global {
${declarations}

  interface Window {
${windowDeclarations}
  }
}

export {};
`;

  writeFileSync(dtsPath, content, "utf-8");
}
