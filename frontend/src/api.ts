/* Typed client for the local backend. The token never leaves this machine. */
import type { PtdBridge } from "../electron/preload";

declare global {
  interface Window { ptd?: PtdBridge }
}

type Info = { port: number; token: string; baseUrl: string; dataDir?: string };
let info: Info | null = null;

export async function initApi(): Promise<Info> {
  if (window.ptd) {
    info = (await window.ptd.backendInfo()) as Info;
  } else {
    // browser fallback (development / automated UI tests): ?port=..&token=..
    const q = new URLSearchParams(location.search);
    const port = Number(q.get("port") || 8765);
    info = { port, token: q.get("token") || "", baseUrl: `http://127.0.0.1:${port}` };
  }
  window.ptd?.onBackendRestarted((i) => { info = i as Info; });
  return info!;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) { super(message); this.status = status; }
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown; form?: FormData; signal?: AbortSignal } = {}): Promise<T> {
  if (!info) await initApi();
  const headers: Record<string, string> = { "X-PTD-Token": info!.token };
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(opts.body); }
  const r = await fetch(info!.baseUrl + path, { method: opts.method || (body ? "POST" : "GET"), headers, body, signal: opts.signal });
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch { /* not json */ }
    throw new ApiError(r.status, msg || `Request failed (${r.status})`);
  }
  const ct = r.headers.get("content-type") || "";
  return (ct.includes("application/json") ? r.json() : (r.blob() as unknown)) as Promise<T>;
}

export function fileUrl(path: string): string {
  if (!info) return "";
  return `${info.baseUrl}${path}${path.includes("?") ? "&" : "?"}t=${encodeURIComponent(info.token)}`;
}

export function fontUrl(family: string, style = "regular") {
  return fileUrl(`/api/fonts/file?family=${encodeURIComponent(family)}&style=${style}`);
}

/** Save a backend file through a native "Save as" dialog. */
export async function saveFile(path: string, defaultName: string): Promise<string | null> {
  const blob = await api<Blob>(path);
  const buf = await blob.arrayBuffer();
  if (window.ptd) return (await window.ptd.saveBuffer(defaultName, buf)) as string | null;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([buf]));
  a.download = defaultName;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  return defaultName;
}

export async function showInFolder(p: string) { if (window.ptd) await window.ptd.showItem(p); }
export async function openPath(p: string) { if (window.ptd) await window.ptd.openPath(p); }

export function upload(path: string, fields: Record<string, string | Blob | undefined | null>, files: File[] = [], fileField = "file") {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) if (v !== undefined && v !== null) fd.append(k, v as string | Blob);
  for (const f of files) fd.append(fileField, f, f.name);
  return api(path, { form: fd });
}

export async function pollJob(id: string, onUpdate: (j: Job) => void, intervalMs = 350): Promise<Job> {
  for (;;) {
    const j = await api<Job>(`/api/jobs/${id}`);
    onUpdate(j);
    if (!["queued", "running"].includes(j.status)) return j;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

// ------------------------------------------------------------------ types
export type Step = { key: string; label: string; status: "pending" | "running" | "done" | "failed" | "skipped"; progress: number; detail: string; started?: number; finished?: number };
export type Issue = { level: "critical" | "warning" | "info"; code: string; message: string; block?: string; page?: number };
export type Job = {
  id: string; kind: string; status: "queued" | "running" | "succeeded" | "needs_review" | "failed"; progress: number;
  document_id: string; template_id: string; batch_id?: string; steps: Step[]; error?: string | null; created: number; finished?: number;
  log?: { ts: number; level: string; message: string }[]; reused?: boolean;
  result?: {
    outputs?: Record<string, string>; export_dir?: string; pages?: number; thumbnails?: string[]; title?: string; template_name?: string;
    validation?: { summary: { critical: number; warning: number; info: number; passed: boolean }; issues: Issue[] };
    counts?: Record<string, number>; stats?: Record<string, number>; warnings?: Issue[];
  };
};
export type Doc = {
  id: string; title: string; folder_id: string | null; kind: string; import_mode: "editable" | "original"; source_name: string; source_path: string;
  page_count: number | null; question_count: number | null; status: string; warnings: Issue[]; template_id: string | null;
  created: number; updated: number; deleted_at: number | null; stats?: Record<string, number>; jobs?: Job[]; exports?: ExportRec[];
};
export type ExportRec = { id: string; document_id: string; job_id: string | null; kind: string; path: string; size: number; created: number; title?: string };
export type Template = { id: string; name: string; category: string; description: string; config: any; is_default: number; builtin: number; created: number; updated: number };
export type Branding = { id: string; name: string; config: any; is_default: number };
export type Asset = { id: string; kind: string; name: string; path: string; width: number; height: number; dpi: number | null; size: number; document_id: string | null; created: number; used_by?: string[] };
export type Block = {
  id: string; type: string; text?: string; title?: string; level?: number; layout?: string; number?: string | null; number_mode?: "auto" | "manual";
  qtype?: string; options?: { label: string; text: string }[]; images?: any[]; points?: number | string | null; difficulty?: string | null; correct?: string | null;
  answer_lines?: number; rows?: string[][]; header_rows?: number; asset?: string; width?: number; height?: number; kind?: string; caption?: string | null;
  lines?: number; style?: Record<string, any>; source?: { page?: number; ocr?: boolean; confidence?: number }; keep_with_prev?: boolean; restart_numbering?: boolean;
};
export type DocModel = { version: number; title: string; meta: any; blocks: Block[]; overlays: any[]; original_pages: { index: number; rotation: number; include: boolean }[] | null };
export type Preview = { url: string; pages: number; positions: Record<string, { page: number; x0: number; y0: number; x1: number; y1: number }[]>; page_size: [number, number]; issues: Issue[]; summary: any; numbers: Record<string, string>; cover_pages: number; page_layouts: Record<string, string> };
