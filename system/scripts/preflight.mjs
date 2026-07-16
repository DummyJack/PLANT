import {
  closeSync,
  existsSync,
  openSync,
  readFileSync,
  statfsSync,
  unlinkSync,
} from "node:fs";
import { spawnSync } from "node:child_process";
import { createServer } from "node:net";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";


const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const projectRoot = resolve(root, "..");

function preflightEnabled() {
  try {
    const config = JSON.parse(readFileSync(resolve(projectRoot, "config.json"), "utf8"));
    const value = config?.preflight?.system;
    return typeof value === "boolean" ? value : true;
  } catch {
    return true;
  }
}

if (!preflightEnabled()) {
  process.exit(0);
}

const errors = [];
const warnings = [];
const npm = process.platform === "win32" ? "npm.cmd" : "npm";

console.log("前端環境檢查");

const packagePath = resolve(root, "package.json");
if (!existsSync(packagePath)) {
  errors.push("找不到 system/package.json");
}

let packageJson = {};
try {
  packageJson = JSON.parse(readFileSync(packagePath, "utf8"));
} catch (error) {
  errors.push(`無法讀取 system/package.json：${error instanceof Error ? error.message : error}`);
}

const declaredPackages = [
  ...Object.keys(packageJson.dependencies ?? {}),
  ...Object.keys(packageJson.devDependencies ?? {}),
];

function dependencyIssues() {
  if (!existsSync(resolve(root, "node_modules"))) {
    return declaredPackages.map((name) => `${name} 未安裝`);
  }
  const issues = declaredPackages
    .filter((name) => !existsSync(resolve(root, "node_modules", name, "package.json")))
    .map((name) => `${name} 未安裝`);

  const lockfilePath = resolve(root, "package-lock.json");
  if (!existsSync(lockfilePath)) {
    issues.push("找不到 package-lock.json");
  } else {
    try {
      const lockfile = JSON.parse(readFileSync(lockfilePath, "utf8"));
      const lockedRoot = lockfile.packages?.[""] ?? {};
      for (const section of ["dependencies", "devDependencies"]) {
        const declared = packageJson[section] ?? {};
        const locked = lockedRoot[section] ?? {};
        for (const [name, version] of Object.entries(declared)) {
          if (locked[name] !== version) {
            issues.push(`package-lock.json 與 ${section}.${name} 不一致`);
          }
        }
      }
    } catch (error) {
      issues.push(`無法讀取 package-lock.json：${error instanceof Error ? error.message : error}`);
    }
  }

  if (!issues.length) {
    const listed = spawnSync(npm, ["ls", "--depth=0", "--json"], {
      cwd: root,
      encoding: "utf8",
      shell: process.platform === "win32",
      stdio: ["ignore", "pipe", "pipe"],
    });
    if (listed.error || listed.status !== 0) {
      issues.push("node_modules 套件版本不完整或與 package.json 不相容");
    }
  }
  return issues;
}

function checkInstallDirectoryWritable() {
  const targetDir = existsSync(resolve(root, "node_modules"))
    ? resolve(root, "node_modules")
    : root;
  const probe = resolve(targetDir, `.plant-package-probe-${process.pid}-${Date.now()}`);
  try {
    const descriptor = openSync(probe, "wx");
    closeSync(descriptor);
    unlinkSync(probe);
  } catch (error) {
    try {
      unlinkSync(probe);
    } catch {}
    throw new Error(`前端套件安裝目錄無法寫入：${targetDir}`, { cause: error });
  }
}

function checkDiskSpace() {
  const disk = statfsSync(root);
  const available = Number(disk.bavail) * Number(disk.bsize);
  const availableMb = Math.floor(available / 1024 / 1024);
  if (available < 1024 ** 3) {
    errors.push(`磁碟可用空間僅剩 ${availableMb} MB，至少需要 1 GB`);
  } else if (available < 2 * 1024 ** 3) {
    warnings.push(`磁碟可用空間僅剩 ${availableMb} MB，建議保留 2 GB`);
  }
}

function portAvailable(port) {
  return new Promise((resolvePort) => {
    const server = createServer();
    server.unref();
    server.once("error", () => resolvePort(false));
    server.listen({ host: "0.0.0.0", port, exclusive: true }, () => {
      server.close(() => resolvePort(true));
    });
  });
}

try {
  checkDiskSpace();
} catch (error) {
  warnings.push(`無法取得磁碟空間：${error instanceof Error ? error.message : error}`);
}

let issues = errors.length ? [] : dependencyIssues();
if (!errors.length && issues.length) {
  const lockfilePath = resolve(root, "package-lock.json");
  const hasLockfile = existsSync(lockfilePath);
  const lockfileOutOfSync = issues.some((issue) => issue.includes("package-lock.json"));
  const installArgs = hasLockfile && !lockfileOutOfSync
    ? ["ci", "--include=dev"]
    : ["install", "--include=dev"];
  console.log(
    `\n前端套件缺失或版本不符，正在自動執行 npm ${installArgs.join(" ")}…`,
  );
  try {
    checkInstallDirectoryWritable();
  } catch (error) {
    errors.push(error instanceof Error ? error.message : String(error));
  }
  if (!errors.length) {
    const result = spawnSync(npm, installArgs, {
      cwd: root,
      stdio: "inherit",
      shell: process.platform === "win32",
    });
    if (result.error || result.status !== 0) {
      errors.push(
        `前端套件自動安裝失敗${result.error ? `：${result.error.message}` : ""}`,
      );
    } else {
      const unresolved = dependencyIssues();
      if (unresolved.length) {
        errors.push(`前端套件修復後仍有問題：${unresolved.join("；")}`);
      }
    }
  }
}

const lifecycle = process.env.npm_lifecycle_event ?? "";
if (!errors.length && lifecycle !== "prebuild" && !(await portAvailable(3000))) {
  errors.push("前端 Port 3000 已被其他程式占用");
}

if (errors.length) {
  console.error("[ERROR] 前端環境檢查失敗");
  errors.forEach((message) => console.error(`[ERROR] ${message}`));
  process.exit(1);
}

warnings.forEach((message) => console.warn(`[WARN] ${message}`));
console.log("[OK] Node.js 可正常執行\n[OK] 前端套件已安裝");
