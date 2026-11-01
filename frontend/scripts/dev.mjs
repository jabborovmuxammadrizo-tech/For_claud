// Development: Vite dev server + Electron (backend started by Electron from ../backend with Python).
import { spawn } from "node:child_process";
import { createServer } from "vite";

await import("./build-electron.mjs");
const server = await createServer({ configFile: "vite.config.ts" });
await server.listen();
const url = "http://localhost:5173";
const electronBin = (await import("electron")).default;
const child = spawn(electronBin, ["."], { stdio: "inherit", env: { ...process.env, VITE_DEV_SERVER_URL: url, PTD_DEV: "1" } });
child.on("exit", async (code) => { await server.close(); process.exit(code ?? 0); });
