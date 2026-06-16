import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

function useLocalhost(value: string | undefined, fallback: boolean): boolean {
  if (value == null || value.trim() === "") return fallback;
  return ["1", "true", "yes", "on"].includes(value.trim().toLowerCase());
}

export default defineConfig(({ mode }) => {
  const envDir = path.resolve(__dirname, "..");
  const env = loadEnv(mode, envDir, ["develop_", "devlop_"]);
  const useLocalFrontend = useLocalhost(env.devlop_frontend, true);

  return {
    plugins: [react()],
    envDir,
    envPrefix: ["develop_", "devlop_"],
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
      allowedHosts: useLocalFrontend ? [] : ["plant.dummyjack.com"],
      proxy: {
        "/api": {
          target: "http://127.0.0.1:8000",
          changeOrigin: true,
        },
      },
    },
  };
});
