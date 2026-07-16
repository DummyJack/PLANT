import { readFileSync, statfsSync } from "node:fs";
import { createServer } from "node:net";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import {
  readFrontendHost,
  validateFrontendHost,
} from "./preflight/frontend-host.mjs";
import {
  findDependencyIssues,
  loadPackageManifest,
  repairDependencies,
} from "./preflight/dependencies.mjs";

const systemRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const projectRoot = resolve(systemRoot, "..");

function readPreflightSetting() {
  const path = resolve(projectRoot, "config.json");
  try {
    const config = JSON.parse(readFileSync(path, "utf8"));
    const value = config?.preflight?.system;
    if (value !== undefined && typeof value !== "boolean") {
      return {
        enabled: true,
        error: `config.json 的 preflight.system 必須是布林值；位置：${path}`,
      };
    }
    return { enabled: value ?? true, error: null };
  } catch (error) {
    return {
      enabled: true,
      error: `無法讀取 config.json ${path}：${error instanceof Error ? error.message : error}`,
    };
  }
}

const preflightSetting = readPreflightSetting();
if (!preflightSetting.enabled && !preflightSetting.error) {
  process.exit(0);
}

const errors = preflightSetting.error ? [preflightSetting.error] : [];
const warnings = [];
const nodeVersion = process.versions.node;
const nodeMajor = Number.parseInt(nodeVersion.split(".", 1)[0], 10);
const supportedNodeVersion = nodeMajor === 18 || nodeMajor === 20 || nodeMajor >= 22;

console.log("前端環境檢查");

if (!supportedNodeVersion) {
  errors.push(
    `不支援 Node.js ${nodeVersion}；Vite 需要 Node.js 18、20 或 22 以上版本`,
  );
}

const frontendHostConfig = readFrontendHost(projectRoot);
if (frontendHostConfig.readError) errors.push(frontendHostConfig.readError);
const configuredFrontendHost = frontendHostConfig.host;
const frontendHostResult = await validateFrontendHost(configuredFrontendHost);
if (frontendHostResult.error) {
  errors.push(
    `frontend_host 無效：${configuredFrontendHost}\n` +
      `        來源：${frontendHostConfig.source}\n` +
      `        原因：${frontendHostResult.error}\n` +
      "        範例：frontend_host=plant.example.com 或 frontend_host=127.0.0.1",
  );
}

const packageManifest = loadPackageManifest(systemRoot);
if (packageManifest.error) errors.push(packageManifest.error);

function checkDiskSpace() {
  const disk = statfsSync(systemRoot);
  const available = Number(disk.bavail) * Number(disk.bsize);
  const availableMb = Math.floor(available / 1024 / 1024);
  if (available < 1024 ** 3) {
    errors.push(`磁碟可用空間僅剩 ${availableMb} MB，至少需要 1 GB`);
  } else if (available < 2 * 1024 ** 3) {
    warnings.push(`磁碟可用空間僅剩 ${availableMb} MB，建議保留 2 GB`);
  }
  return availableMb;
}

function probePort(port) {
  return new Promise((resolvePort) => {
    const server = createServer();
    server.unref();
    server.once("error", (error) => resolvePort({ available: false, error }));
    server.listen({ host: "0.0.0.0", port, exclusive: true }, () => {
      server.close(() => resolvePort({ available: true, error: null }));
    });
  });
}

function portErrorMessage(port, error) {
  if (error?.code === "EADDRINUSE") {
    const command = process.platform === "win32"
      ? `netstat -ano | findstr :${port}`
      : `lsof -nP -iTCP:${port} -sTCP:LISTEN`;
    return `前端 Port ${port} 已被其他程式占用；請關閉占用程序後重試（可用 ${command} 查詢）`;
  }
  if (error?.code === "EACCES") {
    return `沒有權限綁定前端 Port ${port}；請檢查執行帳號與系統權限`;
  }
  const reason = error instanceof Error ? error.message : String(error);
  return `無法檢查前端 Port ${port}：${reason}`;
}

let availableDiskMb;
try {
  availableDiskMb = checkDiskSpace();
} catch (error) {
  warnings.push(`無法取得磁碟空間：${error instanceof Error ? error.message : error}`);
}

const packageIssues = packageManifest.manifest
  ? findDependencyIssues(systemRoot, packageManifest.manifest)
  : [];
if (packageIssues.length) {
  console.log("[INFO] 偵測到以下前端套件問題：");
  packageIssues.forEach((issue) => console.log(`       - ${issue}`));
}
if (!errors.length && packageIssues.length) {
  const repairError = repairDependencies(
    systemRoot,
    packageManifest.manifest,
    packageIssues,
  );
  if (repairError) errors.push(repairError);
}

const lifecycle = process.env.npm_lifecycle_event ?? "";
let frontendPortAvailable;
if (lifecycle !== "prebuild") {
  const portResult = await probePort(3000);
  frontendPortAvailable = portResult.available;
  if (!portResult.available) {
    errors.push(portErrorMessage(3000, portResult.error));
  }
}

if (errors.length) {
  console.error("[ERROR] 前端環境檢查失敗");
  errors.forEach((message) => console.error(`[ERROR] ${message}`));
  process.exit(1);
}

warnings.forEach((message) => console.warn(`[WARN] ${message}`));
console.log(`[OK] Node.js ${nodeVersion}（符合 Vite 版本需求）`);
console.log("[OK] 前端套件完整且版本相容");
console.log(
  `[OK] frontend_host 格式正確：${configuredFrontendHost}（來源：${frontendHostConfig.source}）`,
);
if (frontendHostResult.addresses.length) {
  const displayedAddresses = frontendHostResult.addresses.slice(0, 4);
  const addressSuffix = frontendHostResult.addresses.length > 4 ? "…" : "";
  console.log(
    `[OK] frontend_host DNS 解析成功：${configuredFrontendHost} → ${displayedAddresses.join(", ")}${addressSuffix}`,
  );
} else {
  console.log(`[OK] frontend_host 不需要 DNS 解析：${configuredFrontendHost}`);
}
if (frontendPortAvailable === true) {
  console.log("[OK] 前端 Port 可綁定：0.0.0.0:3000");
}
if (availableDiskMb !== undefined && availableDiskMb >= 2 * 1024) {
  console.log(`[OK] 磁碟可用空間：${availableDiskMb} MB`);
}
