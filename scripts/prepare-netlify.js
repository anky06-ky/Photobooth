import { copyFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

const source = join("models", "hand_landmarker.task");
const targetDir = join("web", "models");
const target = join(targetDir, "hand_landmarker.task");

mkdirSync(targetDir, { recursive: true });
copyFileSync(source, target);

console.log(`Copied ${source} -> ${target}`);
