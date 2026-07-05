import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

const envDir = path.resolve(__dirname, "..");

function isLocalFrontendHost(host: string) {
  return host === "localhost" || host === "127.0.0.1" || host === "::1" || host.endsWith(".localhost");
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, envDir, ["frontend_"]);
  const configuredFrontendHost = env.frontend_host?.trim() || "";
  const frontendHost = configuredFrontendHost || "localhost";
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
      allowedHosts: ["localhost", "127.0.0.1", frontendHost],
      watch: {
        ignored: [
          path.resolve(envDir, ".env"),
          path.resolve(envDir, "config.json"),
        ],
      },
      proxy: {
        "/api": {
          target: "http://127.0.0.1:8000",
          changeOrigin: true,
        },
        "/manual": {
          target: "http://127.0.0.1:8000",
          changeOrigin: true,
        },
        "^/[^/]+/references/[^/]+/preview-file$": {
          target: "http://127.0.0.1:8000",
          changeOrigin: true,
        },
        "^/[^/]+/references/[^/]+$": {
          target: "http://127.0.0.1:8000",
          changeOrigin: true,
        },
        "^/[^/]+/(manual|artifact|results|output)(/.*)?$": {
          target: "http://127.0.0.1:8000",
          changeOrigin: true,
        },
      },
    },
  };
});
