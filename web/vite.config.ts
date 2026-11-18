import { defineConfig } from "vite";
import preact from "@preact/preset-vite";

// In sviluppo le chiamate /api vanno al server Python (uvicorn sulla porta 8000).
export default defineConfig({
  plugins: [preact()],
  server: { proxy: { "/api": "http://localhost:8000" } },
  build: { outDir: "dist", assetsDir: "assets", sourcemap: false },
});
