import type { IncomingMessage, ServerResponse } from "node:http";
import type { ClientRequest } from "node:http";
import { defineConfig, loadEnv } from "vite";

function configureSseProxy(
  proxy: { on: (event: string, fn: (...args: unknown[]) => void) => void },
) {
  proxy.on("proxyRes", (proxyRes: IncomingMessage, _req: ClientRequest, res: ServerResponse) => {
    const ct = String(proxyRes.headers["content-type"] ?? "");
    if (!ct.includes("text/event-stream")) return;
    proxyRes.headers["cache-control"] = "no-cache, no-transform";
    proxyRes.headers["x-accel-buffering"] = "no";
    if (typeof res.flushHeaders === "function") {
      res.flushHeaders();
    }
  });
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiTarget = env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000";

  return {
    root: ".",
    server: {
      port: 5173,
      proxy: {
        "/api": {
          target: apiTarget,
          changeOrigin: true,
          configure: configureSseProxy,
        },
        "/health": { target: apiTarget, changeOrigin: true },
      },
    },
  };
});
