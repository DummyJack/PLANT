import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

const envDir = path.resolve(__dirname, "..");

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, envDir, ["frontend_"]);
  const frontendHost = env.frontend_host?.trim() || "plant.dummyjack.com";

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
      port: 3000,
      allowedHosts: [frontendHost],
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
        "^/[^/]+/(manual|artifact|results|output)(/.*)?$": {
          target: "http://127.0.0.1:8000",
          changeOrigin: true,
        },
      },
    },
  };
});
