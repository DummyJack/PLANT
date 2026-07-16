import {
  closeSync,
  existsSync,
  openSync,
  readFileSync,
  unlinkSync,
} from "node:fs";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

const NPM = process.platform === "win32" ? "npm.cmd" : "npm";
const PACKAGE_SECTIONS = ["dependencies", "devDependencies"];

function errorMessage(error) {
  return error instanceof Error ? error.message : String(error);
}

function conciseOutput(output, maximum = 500) {
  const message = String(output ?? "").trim().replace(/\s+/g, " ");
  return message.length > maximum ? `${message.slice(0, maximum - 3)}...` : message;
}

export function loadPackageManifest(systemRoot) {
  const path = resolve(systemRoot, "package.json");
  if (!existsSync(path)) {
    return { manifest: null, error: `找不到前端套件清單：${path}` };
  }
  try {
    return { manifest: JSON.parse(readFileSync(path, "utf8")), error: null };
  } catch (error) {
    return {
      manifest: null,
      error: `無法讀取前端套件清單 ${path}：${errorMessage(error)}`,
    };
  }
}

function declaredPackages(manifest) {
  return PACKAGE_SECTIONS.flatMap((section) =>
    Object.keys(manifest[section] ?? {}),
  );
}

function lockfileIssues(systemRoot, manifest) {
  const path = resolve(systemRoot, "package-lock.json");
  if (!existsSync(path)) return ["找不到 package-lock.json"];

  try {
    const lockedRoot = JSON.parse(readFileSync(path, "utf8")).packages?.[""] ?? {};
    const issues = [];
    for (const section of PACKAGE_SECTIONS) {
      for (const [name, version] of Object.entries(manifest[section] ?? {})) {
        if (lockedRoot[section]?.[name] !== version) {
          issues.push(`package-lock.json 與 ${section}.${name} 不一致`);
        }
      }
    }
    return issues;
  } catch (error) {
    return [`無法讀取 package-lock.json：${errorMessage(error)}`];
  }
}

export function findDependencyIssues(systemRoot, manifest) {
  const nodeModules = resolve(systemRoot, "node_modules");
  const packages = declaredPackages(manifest);
  const issues = existsSync(nodeModules)
    ? packages
        .filter((name) => !existsSync(resolve(nodeModules, name, "package.json")))
        .map((name) => `${name} 未安裝`)
    : packages.map((name) => `${name} 未安裝`);

  issues.push(...lockfileIssues(systemRoot, manifest));
  if (issues.length) return issues;

  const listed = spawnSync(NPM, ["ls", "--depth=0", "--json"], {
    cwd: systemRoot,
    encoding: "utf8",
    shell: process.platform === "win32",
    stdio: ["ignore", "pipe", "pipe"],
  });
  if (!listed.error && listed.status === 0) return [];
  const reason = conciseOutput(listed.error?.message || listed.stderr);
  return [
    "node_modules 套件版本不完整或與 package.json 不相容" +
      (reason ? `：${reason}` : ""),
  ];
}

function requireInstallDirectoryWritable(systemRoot) {
  const nodeModules = resolve(systemRoot, "node_modules");
  const targetDir = existsSync(nodeModules) ? nodeModules : systemRoot;
  const probe = resolve(
    targetDir,
    `.plant-package-probe-${process.pid}-${Date.now()}`,
  );
  try {
    const descriptor = openSync(probe, "wx");
    closeSync(descriptor);
    unlinkSync(probe);
  } catch (error) {
    try {
      unlinkSync(probe);
    } catch {}
    throw new Error(
      `前端套件安裝目錄無法寫入：${targetDir}（${errorMessage(error)}）`,
      { cause: error },
    );
  }
}

export function repairDependencies(systemRoot, manifest, issues) {
  const lockfileExists = existsSync(resolve(systemRoot, "package-lock.json"));
  const lockfileOutOfSync = issues.some((issue) =>
    issue.includes("package-lock.json"),
  );
  const installArgs = lockfileExists && !lockfileOutOfSync
    ? ["ci", "--include=dev"]
    : ["install", "--include=dev"];

  console.log(
    `\n前端套件缺失或版本不符，正在自動執行 npm ${installArgs.join(" ")}…`,
  );
  try {
    requireInstallDirectoryWritable(systemRoot);
  } catch (error) {
    return errorMessage(error);
  }

  const result = spawnSync(NPM, installArgs, {
    cwd: systemRoot,
    stdio: "inherit",
    shell: process.platform === "win32",
  });
  if (result.error || result.status !== 0) {
    const reason = result.error
      ? `：${result.error.message}`
      : `（npm 結束碼 ${result.status}；請查看上方 npm 輸出）`;
    return `前端套件自動安裝失敗${reason}`;
  }

  const unresolved = findDependencyIssues(systemRoot, manifest);
  return unresolved.length
    ? `前端套件修復後仍有問題：${unresolved.join("；")}`
    : null;
}
