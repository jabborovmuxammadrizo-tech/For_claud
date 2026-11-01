import { contextBridge, ipcRenderer } from "electron";

/** The only privileged API the renderer can use. */
const api = {
  backendInfo: () => ipcRenderer.invoke("backend:info"),
  version: () => ipcRenderer.invoke("app:version"),
  saveBuffer: (defaultName: string, data: ArrayBuffer) => ipcRenderer.invoke("file:saveBuffer", { defaultName, data }),
  saveCopy: (source: string, defaultName: string) => ipcRenderer.invoke("file:saveCopy", { source, defaultName }),
  showItem: (p: string) => ipcRenderer.invoke("shell:showItem", p),
  openPath: (p: string) => ipcRenderer.invoke("shell:openPath", p),
  openDataDir: () => ipcRenderer.invoke("shell:openDataDir"),
  relaunch: () => ipcRenderer.invoke("app:relaunch"),
  checkUpdate: (url: string) => ipcRenderer.invoke("update:check", url),
  shellRequest: (id: string) => ipcRenderer.invoke("shellreq:get", id),
  openMain: (hash: string) => ipcRenderer.invoke("app:openMain", hash),
  notify: (title: string, body: string, open?: string) => ipcRenderer.invoke("app:notify", { title, body, open }),
  chooseFolder: () => ipcRenderer.invoke("dialog:chooseFolder"),
  integration: {
    status: () => ipcRenderer.invoke("integration:status"),
    apply: (settings: Record<string, unknown>) => ipcRenderer.invoke("integration:apply", settings),
    restore: () => ipcRenderer.invoke("integration:restore"),
    registerUser: () => ipcRenderer.invoke("integration:registerUser"),
    unregisterUser: () => ipcRenderer.invoke("integration:unregisterUser"),
  },
  onNavigate: (cb: (hash: string) => void) => {
    const h = (_e: unknown, hash: string) => cb(hash);
    ipcRenderer.on("app:navigate", h);
    return () => ipcRenderer.removeListener("app:navigate", h);
  },
  onBackendRestarted: (cb: (info: unknown) => void) => {
    const h = (_e: unknown, info: unknown) => cb(info);
    ipcRenderer.on("backend:restarted", h);
    return () => ipcRenderer.removeListener("backend:restarted", h);
  },
};

contextBridge.exposeInMainWorld("ptd", api);
export type PtdBridge = typeof api;
