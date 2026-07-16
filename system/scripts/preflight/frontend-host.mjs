import { lookup } from "node:dns/promises";
import { readFileSync } from "node:fs";
import { isIP } from "node:net";
import { resolve } from "node:path";

const DEFAULT_FRONTEND_HOST = "127.0.0.1";
const DNS_TIMEOUT_MS = 5000;
const LOCAL_HOSTS = new Set(["localhost", DEFAULT_FRONTEND_HOST]);
const HOST_LABEL_PATTERN = /^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$/;
const FRONTEND_HOST_PATTERN = /^\s*(?:export\s+)?frontend_host\s*=\s*(.*)$/;

function parseEnvValue(rawValue) {
  const value = rawValue.trim().replace(/\s+#.*$/, "").trim();
  const quote = value[0];
  if (
    value.length >= 2 &&
    (quote === '"' || quote === "'") &&
    value.at(-1) === quote
  ) {
    return value.slice(1, -1).trim();
  }
  return value;
}

function hostFromEnvFile(contents) {
  let host;
  for (const line of contents.split(/\r?\n/)) {
    const match = line.match(FRONTEND_HOST_PATTERN);
    if (match) host = parseEnvValue(match[1]);
  }
  return host;
}

export function readFrontendHost(projectRoot, environment = process.env) {
  if (Object.hasOwn(environment, "frontend_host")) {
    return {
      host: environment.frontend_host?.trim() || DEFAULT_FRONTEND_HOST,
      source: "環境變數 frontend_host",
      readError: null,
    };
  }

  const envPath = resolve(projectRoot, ".env");
  try {
    const host = hostFromEnvFile(readFileSync(envPath, "utf8"));
    return {
      host: host || DEFAULT_FRONTEND_HOST,
      source: host ? envPath : "預設值（.env 未設定 frontend_host）",
      readError: null,
    };
  } catch (error) {
    return {
      host: DEFAULT_FRONTEND_HOST,
      source: `預設值（找不到 ${envPath}）`,
      readError:
        error?.code === "ENOENT"
          ? null
          : `無法讀取 ${envPath}：${error instanceof Error ? error.message : error}`,
    };
  }
}

function validFrontendHost(host) {
  if (host.length > 253 || host.includes("://") || /[/:\s]/.test(host)) {
    return false;
  }
  if (isIP(host)) return true;
  if (/^[\d.]+$/.test(host)) return false;
  return host.split(".").every(
    (label) => label.length <= 63 && HOST_LABEL_PATTERN.test(label),
  );
}

function dnsFailureReason(error) {
  if (error?.code === "ENOTFOUND") return "找不到這個網域的 DNS 記錄";
  if (error?.code === "EAI_AGAIN") return "DNS 服務暫時無法回應";
  return error instanceof Error ? error.message : String(error);
}

async function lookupWithTimeout(host) {
  let timeout;
  const timeoutFailure = new Promise((_, reject) => {
    timeout = setTimeout(
      () => reject(new Error("DNS 查詢超過 5 秒")),
      DNS_TIMEOUT_MS,
    );
    timeout.unref();
  });
  return Promise.race([lookup(host, { all: true }), timeoutFailure]).finally(
    () => clearTimeout(timeout),
  );
}

export async function validateFrontendHost(host) {
  if (!validFrontendHost(host)) {
    return {
      error: "必須是有效的主機名稱或 IP，不可包含協定、Port 或路徑",
      addresses: [],
    };
  }
  if (LOCAL_HOSTS.has(host.toLowerCase()) || isIP(host)) {
    return { error: null, addresses: [] };
  }

  try {
    const records = await lookupWithTimeout(host);
    const addresses = [...new Set(records.map(({ address }) => address))];
    return addresses.length
      ? { error: null, addresses }
      : { error: "DNS 查詢未傳回任何 IP 位址", addresses: [] };
  } catch (error) {
    return {
      error:
        `DNS 解析失敗（${dnsFailureReason(error)}）；` +
        "請確認網域拼字、DNS 記錄及網路連線",
      addresses: [],
    };
  }
}
