import { Archive, FolderOpen, RefreshCw, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import type { Route } from "../App";
import { api } from "../api";
import { Badge, Button, Card, errMsg, Field, fmtBytes, fmtDate, NumberInput, SectionTitle, Select, Spinner, TextInput, Toggle, useDialogs, useToast } from "../components/ui";

type S = { ocr_enabled: boolean; autosave_seconds: number; default_import_mode: string; daily_backup: boolean; language: string; update_url: string; check_updates: boolean; data_dir: string };

export default function SettingsPage(_: { route: Route }) {
  const toast = useToast();
  const { confirm } = useDialogs();
  const [s, setS] = useState<S | null>(null);
  const [info, setInfo] = useState<any>(null);
  const [backups, setBackups] = useState<{ name: string; size: number; created: number }[]>([]);
  const [history, setHistory] = useState<any[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [version, setVersion] = useState<string>("");
  const [upd, setUpd] = useState<string | null>(null);
  const load = useCallback(async () => {
    const [a, b, c, h] = await Promise.all([api<S>("/api/settings"), api("/api/info"), api("/api/backups"), api("/api/history?limit=60")]);
    setS(a); setInfo(b); setBackups(c); setHistory(h);
  }, []);
  useEffect(() => { load(); window.ptd?.version().then((v) => setVersion(String(v))); }, [load]);
  const put = async (patch: Partial<S>) => {
    try { setS(await api<S>("/api/settings", { method: "PUT", body: patch })); } catch (e) { toast("error", errMsg(e)); }
  };
  if (!s || !info) return <div className="flex justify-center py-24"><Spinner /></div>;
  return (
    <div>
      <SectionTitle title="Settings" subtitle="Everything runs offline on this computer." />
      <div className="grid grid-cols-2 gap-6">
        <Card className="p-6 space-y-3">
          <div className="font-semibold text-navy-900 mb-1">Processing</div>
          <Toggle label="OCR for scanned pages (bundled, offline)" checked={s.ocr_enabled} onChange={(v) => put({ ocr_enabled: v })} hint="Recognises text on scanned pages. Results are always marked for proofreading." />
          <Field label="Default import mode"><Select value={s.default_import_mode} onChange={(v) => put({ default_import_mode: v })} options={[{ value: "editable", label: "Mode A — Editable import" }, { value: "original", label: "Mode B — Original page import" }]} /></Field>
          <Field label="Editor autosave interval (seconds)"><NumberInput value={s.autosave_seconds} min={5} max={600} onChange={(v) => put({ autosave_seconds: v ?? 20 })} /></Field>
          <div className="text-xs text-slate-500 pt-2">OCR engine: {info.ocr.rapidocr ? <Badge tone="green">RapidOCR (bundled)</Badge> : info.ocr.tesseract ? <Badge tone="green">Tesseract</Badge> : <Badge tone="red">not available</Badge>}</div>
        </Card>
        <Card className="p-6 space-y-3">
          <div className="font-semibold text-navy-900 mb-1">Data & backups</div>
          <div className="text-xs text-slate-500 break-all">Data folder: {s.data_dir}</div>
          <div className="flex gap-2">
            {window.ptd && <Button size="sm" icon={<FolderOpen className="h-4 w-4" />} onClick={() => window.ptd!.openDataDir()}>Open data folder</Button>}
            <Button size="sm" icon={<Archive className="h-4 w-4" />} loading={busy === "bk"} onClick={async () => {
              setBusy("bk");
              try { const r = await api("/api/backups", { method: "POST" }); toast("success", `Backup created (${fmtBytes(r.size)})`); load(); } catch (e) { toast("error", errMsg(e)); } finally { setBusy(null); }
            }}>Back up now</Button>
          </div>
          <Toggle label="Automatic daily backup" checked={s.daily_backup} onChange={(v) => put({ daily_backup: v })} />
          <div className="max-h-56 overflow-auto divide-y divide-slate-50 border border-slate-100 rounded-lg">
            {backups.map((b) => (
              <div key={b.name} className="flex items-center gap-3 px-3 py-2 text-sm">
                <div className="flex-1 min-w-0"><div className="truncate text-navy-900">{b.name}</div><div className="text-[11px] text-slate-400">{fmtDate(b.created)} · {fmtBytes(b.size)}</div></div>
                <Button size="sm" variant="ghost" icon={<RotateCcw className="h-3.5 w-3.5" />} loading={busy === b.name} onClick={async () => {
                  if (!(await confirm({ title: "Restore this backup?", danger: true, confirmText: "Restore", requireText: "RESTORE",
                    message: <>Documents, templates and settings will be replaced by the backup from {fmtDate(b.created)}. A safety backup of the current state is created first, so this can be undone.</> }))) return;
                  setBusy(b.name);
                  try { const r = await api(`/api/backups/${encodeURIComponent(b.name)}/restore`, { method: "POST" }); toast("success", `Restored. Safety backup: ${r.safety_backup}`); load(); }
                  catch (e) { toast("error", errMsg(e)); } finally { setBusy(null); }
                }}>Restore</Button>
              </div>
            ))}
            {!backups.length && <div className="px-3 py-4 text-sm text-slate-400">No backups yet.</div>}
          </div>
        </Card>
        <Card className="p-6 space-y-3">
          <div className="font-semibold text-navy-900 mb-1">Updates (optional, online)</div>
          <div className="text-xs text-slate-500">The application never needs the internet. If your school provides an update address, you can check it manually. Offline update packages: run the newer installer — your documents are backed up automatically before changes and kept.</div>
          <Field label="Update address (https://…/latest.json)"><TextInput value={s.update_url} onChange={(e) => setS({ ...s, update_url: e.target.value })} onBlur={() => put({ update_url: s.update_url })} placeholder="optional" /></Field>
          <Button size="sm" icon={<RefreshCw className="h-4 w-4" />} disabled={!s.update_url || !window.ptd} onClick={async () => {
            const r = await window.ptd!.checkUpdate(s.update_url) as any;
            setUpd(r.ok ? (r.latest && r.latest !== r.current ? `Version ${r.latest} is available${r.notes ? ` — ${r.notes}` : ""}.${r.url ? ` Download: ${r.url}` : ""}` : `You have the latest version (${r.current}).`) : r.error);
          }}>Check for updates</Button>
          {upd && <div className="text-sm text-slate-600">{upd}</div>}
        </Card>
        <Card className="p-6">
          <div className="font-semibold text-navy-900 mb-2">About</div>
          <div className="text-sm text-slate-600 space-y-1">
            <div><b>PDF Test Designer</b> — MIRZO ULUGBEK NTM</div>
            <div>Application {version || "—"} · engine {info.version}</div>
            <div>Supported files: {info.supported.join(", ")}</div>
            <div>Fonts: {info.fonts.map((f: any) => f.family).join(", ")}</div>
          </div>
          <div className="text-xs text-slate-500 mt-4 space-y-0.5">
            <div className="font-semibold text-slate-600">Editor shortcuts</div>
            <div>Ctrl+Z / Ctrl+Y undo/redo · Ctrl+S save · Ctrl+C / Ctrl+V copy/paste · Ctrl+D duplicate · Del delete · Alt+↑/↓ move</div>
          </div>
        </Card>
        <Card className="p-6 col-span-2">
          <div className="font-semibold text-navy-900 mb-3">Processing log</div>
          <div className="max-h-72 overflow-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-slate-500 border-b border-slate-100"><th className="py-2 font-medium">When</th><th className="font-medium">Document</th><th className="font-medium">Kind</th><th className="font-medium">Status</th><th className="font-medium">Attempts</th><th className="font-medium">Message</th></tr></thead>
              <tbody>
                {history.map((h) => (
                  <tr key={h.id} className="border-b border-slate-50">
                    <td className="py-1.5 text-xs text-slate-500">{fmtDate(h.created)}</td>
                    <td className="truncate max-w-[220px]">{h.title || h.source_name || "—"}</td>
                    <td className="text-xs">{h.kind}</td>
                    <td><Badge tone={h.status === "succeeded" ? "green" : h.status === "failed" ? "red" : h.status === "needs_review" ? "amber" : "blue"}>{h.status}</Badge></td>
                    <td className="text-xs tabular-nums">{h.attempts}</td>
                    <td className="text-xs text-slate-500 truncate max-w-[320px]" title={h.error || ""}>
                      {h.error || ""}
                      {h.status === "failed" && <button className="ml-2 text-royal-700 hover:underline" onClick={async () => { await api(`/api/jobs/${h.id}/retry`, { method: "POST" }); toast("info", "Retry started"); setTimeout(load, 800); }}>Retry</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </div>
  );
}
