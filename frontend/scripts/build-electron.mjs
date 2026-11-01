import { build } from "esbuild";

const common = { bundle: true, platform: "node", target: "node20", external: ["electron"], sourcemap: false, minify: false };
await build({ ...common, entryPoints: ["electron/main.ts"], outfile: "dist-electron/main.js", format: "cjs" });
await build({ ...common, entryPoints: ["electron/preload.ts"], outfile: "dist-electron/preload.js", format: "cjs" });
console.log("electron main + preload built");
