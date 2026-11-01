/**
 * Electron main process.
 *  - starts the bundled Python backend (ptd-backend.exe) on a free loopback port with a per-launch secret token
 *  - serves the renderer from the custom, sandboxed app:// protocol with a strict Content-Security-Policy
 *  - exposes a minimal, validated IPC surface (save dialogs, open folder) through the preload script
 */
import { app, BrowserWindow, dialog, ipcMain, Menu, net as enet, protocol, shell } from "electron";
import { ChildProcess, spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";

const IS_DEV = !!process.env.VITE_DEV_SERVER_URL;
const DEV_URL = process.env.VITE_DEV_SERVER_URL || "";
const APP_TITLE = "PDF Test Designer — Mirzo Ulugbek NTM";

protocol.registerSchemesAsPrivileged([
  { scheme: "app", privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true, stream: true } },
]);

let mainWindow: BrowserWindow | null = null;
let splash: BrowserWindow | null = null;
let backend: ChildProcess | null = null;
let backendInfo: { port: number; token: string; baseUrl: string; dataDir: string } | null = null;
let quitting = false;
let backendRestarts = 0;
const logDir = path.join(app.getPath("userData"), "logs");
fs.mkdirSync(logDir, { recursive: true });
const logStream = fs.createWriteStream(path.join(logDir, "main.log"), { flags: "a" });
const log = (...a: unknown[]) => logStream.write(`${new Date().toISOString()} ${a.map(String).join(" ")}\n`);

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
}

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.once("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const port = (srv.address() as net.AddressInfo).port;
      srv.close(() => resolve(port));
    });
  });
}

function backendCommand(): { cmd: string; args: string[]; cwd: string } {
  if (app.isPackaged) {
    const exe = process.platform === "win32" ? "ptd-backend.exe" : "ptd-backend";
    const dir = path.join(process.resourcesPath, "backend");
    return { cmd: path.join(dir, exe), args: [], cwd: dir };
  }
  const backendDir = path.resolve(__dirname, "..", "..", "backend");
  const py = process.env.PTD_PYTHON || (process.platform === "win32" ? "python" : "python3");
  return { cmd: py, args: [path.join(backendDir, "run_backend.py")], cwd: backendDir };
}

async function startBackend(): Promise<void> {
  const port = await freePort();
  const token = randomBytes(32).toString("hex");
  const { cmd, args, cwd } = backendCommand();
  const fullArgs = [...args, "--port", String(port), "--parent-pid", String(process.pid)];
  if (IS_DEV) fullArgs.push("--dev");
  if (process.env.PTD_DATA_DIR) fullArgs.push("--data-dir", process.env.PTD_DATA_DIR);
  log("starting backend", cmd, fullArgs.join(" "));
  const child = spawn(cmd, fullArgs, {
    cwd,
    env: { ...process.env, PTD_TOKEN: token, PYTHONIOENCODING: "utf-8", PYTHONUNBUFFERED: "1" },
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
  backend = child;
  const blog = fs.createWriteStream(path.join(logDir, "backend-console.log"), { flags: "a" });
  child.stderr?.on("data", (d) => blog.write(d));

  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("The processing engine did not start within 90 seconds.")), 90_000);
    let buf = "";
    child.stdout?.on("data", (d: Buffer) => {
      blog.write(d);
      buf += d.toString("utf8");
      if (buf.includes("PTD_ERROR")) {
        clearTimeout(timer);
        reject(new Error(buf.split("PTD_ERROR")[1].split("\n")[0].trim()));
      } else if (buf.includes(`PTD_READY ${port}`)) {
        clearTimeout(timer);
        resolve();
      }
    });
    child.once("error", (e) => { clearTimeout(timer); reject(e); });
    child.once("exit", (code) => { clearTimeout(timer); reject(new Error(`The processing engine exited (code ${code}).`)); });
  });
  // confirm the HTTP service answers before showing the UI
  const baseUrl = `http://127.0.0.1:${port}`;
  for (let i = 0; i < 50; i++) {
    try {
      const r = await enet.fetch(`${baseUrl}/api/health`);
      if (r.ok) break;
    } catch { /* not yet */ }
    await new Promise((r) => setTimeout(r, 100));
  }
  const info = await (await enet.fetch(`${baseUrl}/api/info`, { headers: { "X-PTD-Token": token } })).json() as { data_dir: string };
  backendInfo = { port, token, baseUrl, dataDir: info.data_dir };
  child.on("exit", (code) => {
    log("backend exited", code);
    backend = null;
    if (!quitting) onBackendCrash(code);
  });
}

async function onBackendCrash(code: number | null) {
  if (backendRestarts < 2) {
    backendRestarts++;
    try {
      await startBackend();
      mainWindow?.webContents.send("backend:restarted", backendInfo);
      return;
    } catch (e) {
      log("restart failed", e);
    }
  }
  if (mainWindow) {
    const r = await dialog.showMessageBox(mainWindow, {
      type: "error", title: APP_TITLE, buttons: ["Restart application", "Close"],
      message: "The processing engine stopped unexpectedly.",
      detail: `Your documents are saved automatically. Exit code: ${code}. Logs: ${logDir}`,
    });
    if (r.response === 0) { app.relaunch(); }
    app.exit(1);
  }
}

function stopBackend() {
  if (!backend) return;
  try {
    if (process.platform === "win32" && backend.pid) {
      spawn("taskkill", ["/pid", String(backend.pid), "/t", "/f"], { windowsHide: true });
    } else {
      backend.kill("SIGTERM");
    }
  } catch (e) { log("stop backend", e); }
}

function csp(port: number) {
  const api = `http://127.0.0.1:${port}`;
  return [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    `img-src 'self' data: blob: ${api}`,
    `font-src 'self' data: ${api}`,
    `connect-src 'self' ${api}`,
    "worker-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'none'",
    "frame-ancestors 'none'",
    "form-action 'none'",
  ].join("; ");
}

function registerAppProtocol() {
  const root = path.join(__dirname, "..", "dist");
  protocol.handle("app", async (request) => {
    const url = new URL(request.url);
    let rel = decodeURIComponent(url.pathname);
    if (rel === "/" || rel === "") rel = "/index.html";
    const file = path.normalize(path.join(root, rel));
    if (!file.startsWith(root)) return new Response("Forbidden", { status: 403 });
    try {
      const data = await fs.promises.readFile(file);
      const ext = path.extname(file).toLowerCase();
      const types: Record<string, string> = {
        ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
        ".svg": "image/svg+xml", ".png": "image/png", ".json": "application/json", ".woff2": "font/woff2", ".ttf": "font/ttf",
        ".ico": "image/x-icon", ".map": "application/json",
      };
      return new Response(data, {
        headers: { "Content-Type": types[ext] || "application/octet-stream", "Content-Security-Policy": csp(backendInfo?.port || 0) },
      });
    } catch {
      return new Response("Not found", { status: 404 });
    }
  });
}

function logoDataUri(): string {
  try {
    const svg = fs.readFileSync(path.join(__dirname, "..", "dist", "logo.svg"));
    return "data:image/svg+xml;base64," + svg.toString("base64");
  } catch {
    return "";
  }
}

function createSplash() {
  splash = new BrowserWindow({ width: 460, height: 300, frame: false, resizable: false, show: true, backgroundColor: "#0F1F4B",
    webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
  const html = `<html><body style="margin:0;font-family:Segoe UI,Roboto,sans-serif;background:#0F1F4B;color:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh">
    <div style="width:84px;height:84px;border-radius:50%;background:#fff;display:flex;align-items:center;justify-content:center"><img src="${logoDataUri()}" style="width:76px;height:76px" alt=""></div>
    <h2 style="margin:18px 0 4px;font-weight:700">PDF Test Designer</h2><div style="opacity:.75;font-size:13px">MIRZO ULUGBEK NTM</div>
    <div style="margin-top:26px;font-size:12px;opacity:.7">Starting the processing engine…</div></body></html>`;
  splash.loadURL("data:text/html;charset=utf-8," + encodeURIComponent(html));
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440, height: 920, minWidth: 1100, minHeight: 700, show: false, title: APP_TITLE, backgroundColor: "#F8FAFC",
    icon: path.join(__dirname, "..", "build", "icon.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true, nodeIntegration: false, sandbox: true, webSecurity: true, spellcheck: false,
      devTools: IS_DEV || !!process.env.PTD_DEVTOOLS,
    },
  });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("https://")) shell.openExternal(url);
    return { action: "deny" };
  });
  mainWindow.webContents.on("will-navigate", (e, url) => {
    if (!(url.startsWith("app://") || (IS_DEV && url.startsWith(DEV_URL)))) e.preventDefault();
  });
  mainWindow.webContents.on("render-process-gone", async (_e, details) => {
    log("renderer gone", details.reason);
    if (quitting || !mainWindow) return;
    await dialog.showMessageBox(mainWindow, { type: "warning", title: APP_TITLE, message: "The window stopped unexpectedly and will be reloaded.",
      detail: "Your document is saved automatically every few seconds." });
    mainWindow.reload();
  });
  mainWindow.once("ready-to-show", () => {
    splash?.destroy();
    splash = null;
    mainWindow?.maximize();
    mainWindow?.show();
  });
  if (IS_DEV) mainWindow.loadURL(DEV_URL);
  else mainWindow.loadURL("app://ptd/index.html");
  mainWindow.on("closed", () => { mainWindow = null; });
}

// ------------------------------------------------------------------ IPC (all inputs validated)
function insideDataDir(p: unknown): string {
  if (typeof p !== "string" || !backendInfo) throw new Error("invalid path");
  const resolved = path.resolve(p);
  const root = path.resolve(backendInfo.dataDir);
  if (!(resolved === root || resolved.startsWith(root + path.sep))) throw new Error("path outside the application data folder");
  return resolved;
}
const str = (v: unknown, max = 260) => (typeof v === "string" ? v.slice(0, max) : "");

ipcMain.handle("backend:info", () => backendInfo);
ipcMain.handle("app:version", () => app.getVersion());
ipcMain.handle("file:saveBuffer", async (_e, args: { defaultName?: unknown; data?: unknown; filters?: unknown }) => {
  if (!mainWindow || !(args?.data instanceof ArrayBuffer || ArrayBuffer.isView(args?.data))) throw new Error("invalid data");
  const name = str(args.defaultName) || "document.pdf";
  const ext = path.extname(name).replace(".", "") || "pdf";
  const r = await dialog.showSaveDialog(mainWindow, {
    defaultPath: path.join(app.getPath("documents"), name.replace(/[\\/:*?"<>|]+/g, "_")),
    filters: [{ name: ext.toUpperCase(), extensions: [ext] }, { name: "All files", extensions: ["*"] }],
  });
  if (r.canceled || !r.filePath) return null;
  const buf = Buffer.from(args.data instanceof ArrayBuffer ? new Uint8Array(args.data) : (args.data as Uint8Array));
  await fs.promises.writeFile(r.filePath, buf);
  return r.filePath;
});
ipcMain.handle("file:saveCopy", async (_e, args: { source?: unknown; defaultName?: unknown }) => {
  if (!mainWindow) return null;
  const src = insideDataDir(args?.source);
  const name = str(args?.defaultName) || path.basename(src);
  const ext = path.extname(name).replace(".", "") || "pdf";
  const r = await dialog.showSaveDialog(mainWindow, {
    defaultPath: path.join(app.getPath("documents"), name.replace(/[\\/:*?"<>|]+/g, "_")),
    filters: [{ name: ext.toUpperCase(), extensions: [ext] }, { name: "All files", extensions: ["*"] }],
  });
  if (r.canceled || !r.filePath) return null;
  if (path.resolve(r.filePath) === src) return r.filePath;
  await fs.promises.copyFile(src, r.filePath);
  return r.filePath;
});
ipcMain.handle("shell:showItem", (_e, p: unknown) => { shell.showItemInFolder(insideDataDir(p)); return true; });
ipcMain.handle("shell:openPath", async (_e, p: unknown) => { const err = await shell.openPath(insideDataDir(p)); return err || true; });
ipcMain.handle("shell:openDataDir", async () => { if (backendInfo) await shell.openPath(backendInfo.dataDir); return true; });
ipcMain.handle("app:relaunch", () => { app.relaunch(); app.exit(0); });
ipcMain.handle("update:check", async (_e, url: unknown) => {
  // optional online update check: never blocks or breaks the app when offline
  const u = str(url, 500);
  if (!u.startsWith("https://")) return { ok: false, error: "Update address must start with https://" };
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 8000);
    const r = await enet.fetch(u, { signal: ctrl.signal });
    clearTimeout(t);
    const j = (await r.json()) as { version?: string; url?: string; notes?: string };
    return { ok: true, current: app.getVersion(), latest: j.version, url: j.url?.startsWith("https://") ? j.url : undefined, notes: j.notes };
  } catch (e) {
    return { ok: false, error: `Could not reach the update server (${(e as Error).message}). The application keeps working offline.` };
  }
});

app.whenReady().then(async () => {
  Menu.setApplicationMenu(null);
  registerAppProtocol();
  createSplash();
  try {
    await startBackend();
  } catch (e) {
    log("backend start failed", e);
    splash?.destroy();
    await dialog.showMessageBox({ type: "error", title: APP_TITLE, message: "PDF Test Designer could not start its processing engine.",
      detail: `${(e as Error).message}\n\nLogs: ${logDir}` });
    app.exit(1);
    return;
  }
  createWindow();
});

app.on("before-quit", () => { quitting = true; stopBackend(); });
app.on("window-all-closed", () => { quitting = true; stopBackend(); app.quit(); });
process.on("uncaughtException", (e) => log("uncaught", e.stack || e));
