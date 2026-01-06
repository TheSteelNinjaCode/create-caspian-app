import { writeFile } from "fs";
import { join, basename, normalize, relative, sep } from "path";
import caspianConfigJson from "../caspian.config.json";
import { promises as fsPromises } from "fs";
import { generateFileListJson } from "./files-list";
import { componentMap } from "./component-map";

const currentProjectRoot = process.cwd();
const newProjectName = basename(currentProjectRoot);
const configFilePath = join(currentProjectRoot, "caspian.config.json");

function updateProjectNameInConfig(
  filePath: string,
  newProjectName: string,
  currentRoot: string
): void {
  const newWebPath = calculateDynamicWebPath(
    currentRoot,
    caspianConfigJson.projectRootPath,
    caspianConfigJson.bsPathRewrite?.["^/"]
  );

  caspianConfigJson.projectName = newProjectName;
  caspianConfigJson.projectRootPath = currentRoot;
  caspianConfigJson.bsTarget = `http://localhost${newWebPath}`;

  if (!caspianConfigJson.bsPathRewrite) {
    (caspianConfigJson as any).bsPathRewrite = {};
  }
  caspianConfigJson.bsPathRewrite["^/"] = newWebPath;

  writeFile(
    filePath,
    JSON.stringify(caspianConfigJson, null, 2),
    "utf8",
    (err) => {
      if (err) {
        console.error("Error writing the updated JSON file:", err);
        return;
      }
      console.log(
        `Configuration updated.\nProject: ${newProjectName}\nURL: http://localhost${newWebPath}`
      );
    }
  );
}

function calculateDynamicWebPath(
  currentPath: string,
  oldPath?: string,
  oldUrl?: string
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
    } catch (e) {}
  }

  if (webRoot) {
    const relPath = relative(webRoot, currentPath);
    const urlPath = relPath.split(sep).join("/");
    return `/${urlPath}/`.replace(/\/+/g, "/");
  }

  return "/";
}

updateProjectNameInConfig(configFilePath, newProjectName, currentProjectRoot);

export const deleteFilesIfExist = async (
  filePaths: string[]
): Promise<void> => {
  for (const filePath of filePaths) {
    try {
      await fsPromises.unlink(filePath);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
        console.error(`Error deleting ${filePath}:`, error);
      }
    }
  }
};

export async function deleteDirectoriesIfExist(
  dirPaths: string[]
): Promise<void> {
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

export const filesToDelete = [
  join(currentProjectRoot, "settings", "component-map.json"),
];

export const dirsToDelete = [
  join(currentProjectRoot, "caches"),
  join(currentProjectRoot, ".casp"),
];

await deleteFilesIfExist(filesToDelete);
await deleteDirectoriesIfExist(dirsToDelete);
await generateFileListJson();
await componentMap();
