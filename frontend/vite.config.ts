import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const api = env.VITE_API_TARGET || "http://localhost:8080";
  const ws = api.replace(/^http/, "ws");
  return {
    plugins: [react()],
    resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
    server: {
      port: 5173,
      proxy: {
        "/api": api,
        "/media": api,
        "/live": api,
        "/ws": { target: ws, ws: true },
      },
    },
    build: {
      chunkSizeWarningLimit: 2500,
      rollupOptions: {
        output: {
          manualChunks: {
            react: ["react", "react-dom", "react-router-dom"],
            antd: ["antd", "@ant-design/icons"],
            echarts: ["echarts"],
            konva: ["konva", "react-konva"],
            rjsf: ["@rjsf/core", "@rjsf/antd", "@rjsf/utils", "@rjsf/validator-ajv8"],
          },
        },
      },
    },
  };
});
