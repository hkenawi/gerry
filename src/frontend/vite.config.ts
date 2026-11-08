/** Configure local API forwarding and browser-component tests. */
import { defineConfig } from "vitest/config";

const backendUrl = "http://127.0.0.1:8080";

export default defineConfig({
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/health": backendUrl,
      "/chat": backendUrl,
    },
  },
  test: { environment: "jsdom" },
});
