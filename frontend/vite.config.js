import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { fileURLToPath } from "node:url";
var __dirname = path.dirname(fileURLToPath(import.meta.url));
export default defineConfig({
    base: "/ui/",
    plugins: [react()],
    resolve: {
        alias: {
            "@": path.resolve(__dirname, "src"),
        },
    },
    test: {
        environment: "jsdom",
        setupFiles: "./src/test/setup.ts",
    },
    build: {
        outDir: "dist",
        emptyOutDir: true,
    },
});
