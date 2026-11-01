/**
 * Electron main process.
 *  - starts the bundled Python backend (ptd-backend.exe) on a free loopback port with a per-launch secret token
 *  - serves the renderer from the custom, sandboxed app:// protocol with a strict Content-Security-Policy
 *  - exposes a minimal, validated IPC surface (save dialogs, open folder) through the preload script
 */
import { app, BrowserWindow, dialog, ipcMain, Menu, net as enet, Notification, protocol, shell } from "electron";
import { ChildProcess, spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import * as SI from "./shellIntegration";

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

app.setAppUserModelId("uz.mirzoulugbek.pdftestdesigner");

// ------------------------------------------------------------------ Explorer right-click requests
// Explorer starts "PDF Test Designer.exe --shell=<command> <path>" once per selected item. The first
// process owns the single-instance lock; the others forward their arguments here and exit, so a
// multi-selection arrives as several requests that are grouped into one task.
type ShellReq = { id: string; command: string; paths: string[]; pick: boolean; created: number };
const shellRequests = new Map<string, ShellReq>();
const pendingShell = new Map<string, { paths: Set<string>; pick: boolean; command: string; timer: NodeJS.Timeout }>();
const recentShell = new Map<string, number>();
let backendReady: Promise<void> | null = null;

function parseShellArgs(argv: string[]): { command: string; paths: string[]; pick: boolean } | null {
  const i = argv.findIndex((a) => a.startsWith("--shell="));
  if (i < 0) return null;
  const command = argv[i].slice("--shell=".length);
  if (!/^[a-z][a-z-]{1,30}$/.test(command)) return null;
  // Chromium may reorder the forwarded argv: take every absolute path except the application's own files
  const own = new Set([path.resolve(app.getAppPath()), path.resolve(process.execPath)].map((x) => x.toLowerCase()));
  const paths = argv.filter((a, k) => k > 0 && !a.startsWith("--") && path.isAbsolute(a) && !own.has(path.resolve(a).toLowerCase()) && fs.existsSync(a))
    .slice(0, 5000);
  return { command, paths, pick: argv.includes("--pick-template") || command === "generate-template" };
}

function queueShell(r: { command: string; paths: string[]; pick: boolean }) {
  const key = `${r.command}|${r.pick}`;
  const cur = pendingShell.get(key) || { paths: new Set<string>(), pick: r.pick, command: r.command, timer: setTimeout(() => {}, 0) };
  r.paths.forEach((p) => cur.paths.add(p));
  clearTimeout(cur.timer);
  cur.timer = setTimeout(() => { pendingShell.delete(key); dispatchShell(cur.command, [...cur.paths], cur.pick); }, 900);
  pendingShell.set(key, cur);
}

async function dispatchShell(command: string, paths: string[], pick: boolean) {
  const sig = `${command}|${pick}|${[...paths].sort().join("|")}`;
  const now = Date.now();
  for (const [k, t] of recentShell) if (now - t > 20000) recentShell.delete(k);
  if (recentShell.has(sig)) { log("duplicate shell request ignored", command); return; }
  recentShell.set(sig, now);
  const id = randomBytes(8).toString("hex");
  shellRequests.set(id, { id, command, paths, pick, created: now });
  await backendReady;
  openTaskWindow(id);
}

function openTaskWindow(id: string) {
  const w = new BrowserWindow({
    width: 600, height: 720, minWidth: 480, minHeight: 520, title: "PDF Test Designer — Task", backgroundColor: "#F8FAFC", show: false,
    icon: path.join(__dirname, "..", "build", "icon.png"),
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, nodeIntegration: false, sandbox: true, spellcheck: false,
      devTools: IS_DEV || !!process.env.PTD_DEVTOOLS },
  });
  w.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  w.webContents.on("will-navigate", (e, url) => { if (!(url.startsWith("app://") || (IS_DEV && url.startsWith(DEV_URL)))) e.preventDefault(); });
  w.once("ready-to-show", () => { splash?.destroy(); splash = null; w.show(); w.focus(); });
  w.loadURL(IS_DEV ? `${DEV_URL}#/task/${id}` : `app://ptd/index.html#/task/${id}`);
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", (_e, argv) => {
    const r = parseShellArgs(argv);
    if (r && r.paths.length) { queueShell(r); return; }
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    } else if (backendInfo) {
      createWindow();
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

function createWindow(hash = "") {
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
  if (IS_DEV) mainWindow.loadURL(`${DEV_URL}${hash ? "#/" + hash : ""}`);
  else mainWindow.loadURL(`app://ptd/index.html${hash ? "#/" + hash : ""}`);
  mainWindow.on("closed", () => { mainWindow = null; });
}

// ------------------------------------------------------------------ IPC (all inputs validated)
async function backendJson(p: string, init?: { method?: string; body?: unknown }) {
  if (!backendInfo) throw new Error("engine not running");
  const r = await enet.fetch(backendInfo.baseUrl + p, { method: init?.method || "GET", headers: { "X-PTD-Token": backendInfo.token, "Content-Type": "application/json" },
    body: init?.body !== undefined ? JSON.stringify(init.body) : undefined });
  return r.json();
}

/** Only files inside the data folder or the configured output folder may be opened/revealed. */
async function insideDataDir(p: unknown): Promise<string> {
  if (typeof p !== "string" || !backendInfo) throw new Error("invalid path");
  const resolved = path.resolve(p);
  const roots = [path.resolve(backendInfo.dataDir)];
  try {
    const st = await backendJson("/api/settings");
    if (st.output_dir) roots.push(path.resolve(st.output_dir));
  } catch { /* data folder only */ }
  const norm = (x: string) => (process.platform === "win32" ? x.toLowerCase() : x);
  if (!roots.some((root) => norm(resolved) === norm(root) || norm(resolved).startsWith(norm(root) + path.sep))) throw new Error("path outside the application folders");
  return resolved;
}
const str = (v: unknown, max = 260) => (typeof v === "string" ? v.slice(0, max) : "");

ipcMain.handle("backend:info", () => backendInfo);
ipcMain.handle("app:version", () => app.getVersion());
ipcMain.handle("file:saveBuffer", async (e, args: { defaultName?: unknown; data?: unknown; filters?: unknown }) => {
  const win = BrowserWindow.fromWebContents(e.sender);
  if (!win || !(args?.data instanceof ArrayBuffer || ArrayBuffer.isView(args?.data))) throw new Error("invalid data");
  const name = str(args.defaultName) || "document.pdf";
  const ext = path.extname(name).replace(".", "") || "pdf";
  const r = await dialog.showSaveDialog(win, {
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
  const src = await insideDataDir(args?.source);
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
ipcMain.handle("shell:showItem", async (_e, p: unknown) => { shell.showItemInFolder(await insideDataDir(p)); return true; });
ipcMain.handle("shell:openPath", async (_e, p: unknown) => { const err = await shell.openPath(await insideDataDir(p)); return err || true; });
ipcMain.handle("shellreq:get", (_e, id: unknown) => shellRequests.get(str(id, 40)) || null);
ipcMain.handle("app:openMain", (_e, hash: unknown) => {
  const h = str(hash, 200).replace(/[^A-Za-z0-9_/?=&.-]/g, "");
  if (mainWindow) { mainWindow.webContents.send("app:navigate", h); mainWindow.show(); mainWindow.focus(); }
  else createWindow(h);
  return true;
});
ipcMain.handle("app:notify", async (_e, n: { title?: unknown; body?: unknown; open?: unknown }) => {
  if (!Notification.isSupported()) return false;
  const open = typeof n?.open === "string" ? await insideDataDir(n.open).catch(() => null) : null;
  const note = new Notification({ title: str(n?.title, 120) || "PDF Test Designer", body: str(n?.body, 400), icon: path.join(__dirname, "..", "build", "icon.png") });
  if (open) note.on("click", () => { shell.openPath(open); });
  note.show();
  return true;
});
ipcMain.handle("dialog:chooseFolder", async (e) => {
  const win = BrowserWindow.fromWebContents(e.sender);
  const r = win ? await dialog.showOpenDialog(win, { properties: ["openDirectory", "createDirectory"] }) : null;
  return r && !r.canceled && r.filePaths[0] ? r.filePaths[0] : null;
});
const exePath = () => {
  if (!app.isPackaged) throw new Error("Explorer integration is available in the installed application.");
  return process.execPath;
};
ipcMain.handle("integration:status", async () => ({ ...(await SI.status()), packaged: app.isPackaged, exe: app.isPackaged ? process.execPath : null }));
ipcMain.handle("integration:apply", async (_e, settings: unknown) => {
  if (!SI.supported()) return { ok: false, error: "Windows Explorer integration is only available on Windows." };
  try { await SI.applyToggles((settings || {}) as Record<string, unknown>, exePath()); return { ok: true }; }
  catch (err) { return { ok: false, error: (err as Error).message }; }
});
ipcMain.handle("integration:restore", async () => {
  if (!SI.supported()) return { ok: false, error: "Windows only." };
  try { await SI.restoreDefaults(exePath()); return { ok: true }; } catch (err) { return { ok: false, error: (err as Error).message }; }
});
ipcMain.handle("integration:registerUser", async () => {
  if (!SI.supported()) return { ok: false, error: "Windows only." };
  try { await SI.registerUser(exePath()); return { ok: true }; } catch (err) { return { ok: false, error: (err as Error).message }; }
});
ipcMain.handle("integration:unregisterUser", async () => {
  if (!SI.supported()) return { ok: false, error: "Windows only." };
  try { await SI.unregisterUser(); return { ok: true }; } catch (err) { return { ok: false, error: (err as Error).message }; }
});
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
  const initialShell = parseShellArgs(process.argv);
  let resolveReady: () => void = () => {};
  backendReady = new Promise<void>((r) => { resolveReady = r; });
  if (initialShell && initialShell.paths.length) queueShell(initialShell);
  try {
    await startBackend();
    resolveReady();
  } catch (e) {
    log("backend start failed", e);
    splash?.destroy();
    await dialog.showMessageBox({ type: "error", title: APP_TITLE, message: "PDF Test Designer could not start its processing engine.",
      detail: `${(e as Error).message}\n\nLogs: ${logDir}` });
    app.exit(1);
    return;
  }
  if (initialShell && initialShell.paths.length) {
    // right-click launch: work in the background (task window only) unless the user disabled it
    const st = await backendJson("/api/settings").catch(() => ({ shell_background: true }));
    if (st.shell_background === false) createWindow();
    return;
  }
  createWindow();
});

app.on("before-quit", () => { quitting = true; stopBackend(); });
app.on("window-all-closed", () => { quitting = true; stopBackend(); app.quit(); });
process.on("uncaughtException", (e) => log("uncaught", e.stack || e));
