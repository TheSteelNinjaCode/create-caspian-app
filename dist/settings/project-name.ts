import { promises as fsPromises } from "fs";
import { join, basename, normalize, relative, sep } from "path";
import process from "process";
import caspianConfigJson from "../caspian.config.json";
import { generateFileListJson } from "./files-list.js";
import { componentMap } from "./component-map.js";

const currentProjectRoot = process.cwd();
const newProjectName = basename(currentProjectRoot);
const configFilePath = join(currentProjectRoot, "caspian.config.json");

async function updateProjectNameInConfig(
  filePath: string,
  newProjectName: string,
  currentRoot: string,
): Promise<void> {
  const newWebPath = calculateDynamicWebPath(
    currentRoot,
    caspianConfigJson.projectRootPath,
    caspianConfigJson.bsPathRewrite?.["^/"],
  );

  const nextConfig = {
    ...caspianConfigJson,
    projectName: newProjectName,
    projectRootPath: currentRoot,
    bsTarget: `http://localhost${newWebPath}`,
    bsPathRewrite: {
      ...(caspianConfigJson.bsPathRewrite ?? {}),
      "^/": newWebPath,
    },
  };

  await fsPromises.writeFile(
    filePath,
    JSON.stringify(nextConfig, null, 2),
    "utf8",
  );

  console.log(
    `Configuration updated.\nProject: ${newProjectName}\nURL: http://localhost${newWebPath}`,
  );
}

function calculateDynamicWebPath(
  currentPath: string,
  oldPath?: string,
  oldUrl?: string,
): string {
  let webRoot: string | null = null;

  if (oldPath && oldUrl) {
    try {
      const normOldPath = normalize(oldPath);
      const normOldUrl = normalize(oldUrl).replace(/^[\\\/]|[\\\/]$/g, "");

      if (normOldPath.endsWith(normOldUrl)) {
        webRoot = normOldPath.slice(0, -normOldUrl.length);
        if (webRoot.endsWith(sep)) webRoot = webRoot.slice(0, -1);
      }
    } catch {}
  }

  if (webRoot) {
    const relPath = relative(webRoot, currentPath);
    const urlPath = relPath.split(sep).join("/");
    return `/${urlPath}/`.replace(/\/+/g, "/");
  }

  return "/";
}

async function deleteFilesIfExist(filePaths: string[]): Promise<void> {
  for (const filePath of filePaths) {
    try {
      await fsPromises.unlink(filePath);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
        console.error(`Error deleting ${filePath}:`, error);
      }
    }
  }
}

async function deleteDirectoriesIfExist(dirPaths: string[]): Promise<void> {
  for (const dirPath of dirPaths) {
    try {
      await fsPromises.rm(dirPath, { recursive: true, force: true });
      console.log(`Deleted directory: ${dirPath}`);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
        console.error(`Error deleting directory (${dirPath}):`, error);
      }
    }
  }
}

const filesToDelete = [
  join(currentProjectRoot, "settings", "component-map.json"),
];

const dirsToDelete = [
  join(currentProjectRoot, "caches"),
  join(currentProjectRoot, ".casp"),
];

async function main(): Promise<void> {
  await updateProjectNameInConfig(
    configFilePath,
    newProjectName,
    currentProjectRoot,
  );
  await deleteFilesIfExist(filesToDelete);
  await deleteDirectoriesIfExist(dirsToDelete);
  await generateFileListJson();
  await componentMap();
}

void main().catch((error) => {
  console.error("Failed to prepare workspace metadata:", error);
  process.exit(1);
});
