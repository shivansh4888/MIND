import fs from "fs/promises";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const extensionRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(extensionRoot, "..");
const serverRoot = path.join(extensionRoot, "server");

async function removeDir(target) {
  await fs.rm(target, { recursive: true, force: true });
}

async function copyDir(source, target) {
  await fs.mkdir(target, { recursive: true });
  const entries = await fs.readdir(source, { withFileTypes: true });
  for (const entry of entries) {
    if (
      entry.name === "__pycache__" ||
      entry.name.endsWith(".pyc") ||
      entry.name === ".env"
    ) {
      continue;
    }

    const src = path.join(source, entry.name);
    const dest = path.join(target, entry.name);
    if (entry.isDirectory()) {
      await copyDir(src, dest);
    } else {
      await fs.copyFile(src, dest);
    }
  }
}

async function main() {
  await removeDir(serverRoot);
  await fs.mkdir(serverRoot, { recursive: true });
  await copyDir(path.join(repoRoot, "backend"), path.join(serverRoot, "backend"));
  await fs.copyFile(path.join(repoRoot, "run_server.py"), path.join(serverRoot, "run_server.py"));
  await fs.copyFile(path.join(repoRoot, "requirements.txt"), path.join(serverRoot, "requirements.txt"));
}

main().catch((error) => {
  console.error("[codebase-agent] Failed to prepare bundled server:", error);
  process.exitCode = 1;
});
