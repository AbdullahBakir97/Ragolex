// Builds the embeddable chat widget into dist/widget.js: one script, no
// other files, for websites to load with a single <script> tag.
import { fileURLToPath, URL } from "node:url";

import { defineConfig } from "vite";

export default defineConfig({
  build: {
    outDir: "dist",
    emptyOutDir: false,
    lib: {
      entry: fileURLToPath(new URL("./src/widget/embed.ts", import.meta.url)),
      name: "RagolexWidget",
      formats: ["iife"],
      fileName: () => "widget.js",
    },
    target: "es2020",
  },
});
