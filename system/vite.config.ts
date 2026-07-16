import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

const envDir = path.resolve(__dirname, "..");

function validPort(value: unknown): number | null {
  const port = Number(value);
  return Number.isInteger(port) && port >= 1 && port <= 65535 ? port : null;
}

function isLocalFrontendHost(host: string) {
  return host === "127.0.0.1";
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, envDir, ["frontend_", "backend_"]);
  const configuredFrontendHost = env.frontend_host?.trim() || "";
  const frontendHost = configuredFrontendHost || "127.0.0.1";
  const backendPort = validPort(env.backend_port) ?? 8000;
  const backendProxy = {
    target: `http://127.0.0.1:${backendPort}`,
    changeOrigin: true,
  };
  const serverHost =
    configuredFrontendHost && !isLocalFrontendHost(configuredFrontendHost)
      ? "0.0.0.0"
      : "127.0.0.1";

  return {
    plugins: [react()],
    envDir,
    envPrefix: ["frontend_"],
    build: {
      rollupOptions: {
        output: {
          manualChunks(id) {
            return id.includes("node_modules") ? "vendor" : undefined;
          },
        },
      },
    },
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    server: {
      host: serverHost,
      port: 3000,
      strictPort: true,
      allowedHosts: ["localhost", "127.0.0.1", frontendHost],
      watch: {
        ignored: [
          path.resolve(envDir, ".env"),
          path.resolve(envDir, "config.json"),
        ],
      },
      proxy: {
        "/api": { ...backendProxy },
        "/manual": { ...backendProxy },
        "^/[^/]+/manual\\.zip$": { ...backendProxy },
        "^/[^/]+/references/[^/]+/preview-file$": { ...backendProxy },
        "^/[^/]+/references/[^/]+$": { ...backendProxy },
        "^/[^/]+/(manual|artifact|results|output)(/.*)?$": { ...backendProxy },
      },
    },
  };
});
