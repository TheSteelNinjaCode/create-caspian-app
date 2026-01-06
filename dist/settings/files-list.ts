import { existsSync, readdirSync, statSync, writeFileSync } from "fs";
import { join, sep, relative } from "path";
import { getFileMeta } from "./utils.js";
import { PUBLIC_DIR, APP_DIR } from "../settings/utils.js";

const { __dirname } = getFileMeta();

const jsonFilePath = "settings/files-list.json";

const getAllFiles = (dirPath: string): string[] => {
  const files: string[] = [];

  if (!existsSync(dirPath)) {
    console.error(`Directory not found: ${dirPath}`);
    return files;
  }

  const items = readdirSync(dirPath);
  items.forEach((item) => {
    const fullPath = join(dirPath, item);
    if (statSync(fullPath).isDirectory()) {
      files.push(...getAllFiles(fullPath));
    } else {
      const relativePath = `.${sep}${relative(
        join(__dirname, ".."),
        fullPath
      )}`;
      files.push(relativePath.replace(/\\/g, "/").replace(/^\.\.\//, ""));
    }
  });

  return files;
};

export const generateFileListJson = async (): Promise<void> => {
  const appFiles = getAllFiles(APP_DIR);
  const publicFiles = getAllFiles(PUBLIC_DIR);

  const allFiles = [...appFiles, ...publicFiles];

  if (allFiles.length > 0) {
    writeFileSync(jsonFilePath, JSON.stringify(allFiles, null, 2));
    console.log(
      `File list generated: ${appFiles.length} app files, ${publicFiles.length} public files`
    );
  } else {
    console.error("No files found to save in the JSON file.");
  }
};
