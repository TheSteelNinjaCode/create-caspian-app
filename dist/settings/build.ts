import { generateFileListJson } from "./files-list.js";
import {
  deleteFilesIfExist,
  filesToDelete,
  deleteDirectoriesIfExist,
  dirsToDelete,
} from "./project-name.js";
import { componentMap } from "./component-map.js";

(async () => {
  console.log("📦 Generating files for production...");

  await deleteFilesIfExist(filesToDelete);
  await deleteDirectoriesIfExist(dirsToDelete);
  await generateFileListJson();
  await componentMap();

  console.log("✅ Generating files for production completed.");
})();
