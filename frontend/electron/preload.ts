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
  onBackendRestarted: (cb: (info: unknown) => void) => {
    const h = (_e: unknown, info: unknown) => cb(info);
    ipcRenderer.on("backend:restarted", h);
    return () => ipcRenderer.removeListener("backend:restarted", h);
  },
};

contextBridge.exposeInMainWorld("ptd", api);
export type PtdBridge = typeof api;
