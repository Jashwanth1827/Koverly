import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, "VITE_");

  return {
    plugins: [react()],
    resolve: {
      alias: { "@": path.resolve(__dirname, "./src") },
    },
    server: {
      host: true,
      port: 5173,
      allowedHosts: true,
      proxy: {
        "/api": {
          // 127.0.0.1 avoids an IPv6 `localhost` resolution on Windows, where
          // uvicorn binds IPv4 by default and the proxy would otherwise fail.
          target: env.VITE_API_PROXY || "http://127.0.0.1:8000",
          changeOrigin: true,
        },
      },
    },
  };
});