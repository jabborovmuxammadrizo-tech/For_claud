import { Download, FileArchive, FileText, RefreshCw, X, Zap } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { navigate, Route } from "../App";
import { api, Job, saveFile, Template, upload } from "../api";
import { Badge, Button, Card, Dropzone, errMsg, fmtBytes, fmtDate, Progress, SectionTitle, Select, Spinner, useToast } from "../components/ui";
import { StatusBadge } from "./Dashboard";
import { ACCEPT } from "./QuickGenerator";

type BatchJob = { id: string; status: Job["status"]; progress: number; error: string | null; document_id: string; title: string; source_name: string; steps: Job["steps"]; result: Job["result"] };
type BatchRec = { id: string; name: string; created: number; template_name: string; jobs: BatchJob[]; progress: number; counts: Record<string, number>; finished: boolean; upload_errors?: { file: string; error: string }[] };

export default function Batch(_: { route: Route }) {
  const toast = useToast();
  const [files, setFiles] = useState<File[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [tid, setTid] = useState("");
  const [batch, setBatch] = useState<BatchRec | null>(null);
  const [history, setHistory] = useState<BatchRec[]>([]);
  const [starting, setStarting] = useState(false);
  const loadHistory = useCallback(() => api<BatchRec[]>("/api/batches").then(setHistory), []);
  useEffect(() => {
    api<Template[]>("/api/templates").then((t) => { setTemplates(t); setTid((t.find((x) => x.is_default) || t[0])?.id || ""); });
    loadHistory();
  }, [loadHistory]);
  useEffect(() => {
    if (!batch || batch.finished) return;
    const t = setTimeout(async () => {
      try { const b = await api<BatchRec>(`/api/batches/${batch.id}`); setBatch(b); if (b.finished) loadHistory(); } catch (e) { toast("error", errMsg(e)); }
    }, 600);
    return () => clearTimeout(t);
  }, [batch, loadHistory, toast]);

  const start = async () => {
    setStarting(true);
    try {
      const b = await upload("/api/batches", { template_id: tid }, files, "files");
      setBatch(b); setFiles([]);
      for (const e of b.upload_errors || []) toast("error", `${e.file}: ${e.error}`);
    } catch (e) { toast("error", errMsg(e)); } finally { setStarting(false); }
  };

  return (
    <div>
      <SectionTitle title="Batch Generator" subtitle="Process many examinations with the same template. Each document keeps its own content and gets the same branding." />
      {!batch ? (
        <div className="grid grid-cols-3 gap-6">
          <Card className="col-span-2 p-6">
            <div className="font-semibold text-navy-900 mb-3">1. Upload documents</div>
            <Dropzone multiple accept={ACCEPT} onFiles={(f) => setFiles((x) => [...x, ...f])} title="Select multiple PDF / DOCX files" subtitle="or drag and drop them here" />
            {files.length > 0 && (
              <div className="mt-4 divide-y divide-slate-100 border border-slate-100 rounded-lg">
                {files.map((f, i) => (
                  <div key={i} className="flex items-center gap-3 px-3 py-2 text-sm">
                    <FileText className="h-4 w-4 text-royal-600" /><span className="flex-1 truncate">{f.name}</span><span className="text-xs text-slate-400">{fmtBytes(f.size)}</span>
                    <button onClick={() => setFiles(files.filter((_, k) => k !== i))} className="text-slate-400 hover:text-brandred-600" aria-label="Remove"><X className="h-4 w-4" /></button>
                  </div>
                ))}
              </div>
            )}
          </Card>
          <Card className="p-6 flex flex-col">
            <div className="font-semibold text-navy-900 mb-3">2. Choose template</div>
            <Select value={tid} onChange={setTid} options={templates.map((t) => ({ value: t.id, label: t.name }))} />
            <div className="flex-1" />
            <div className="font-semibold text-navy-900 mt-6 mb-3">3. Generate</div>
            <Button variant="hero" size="lg" icon={<Zap className="h-5 w-5" />} disabled={!files.length || !tid} loading={starting} onClick={start}>GENERATE ALL ({files.length})</Button>
          </Card>
        </div>
      ) : (
        <Card className="p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="font-semibold text-navy-900">{batch.name}</div>
              <div className="text-xs text-slate-500">{batch.jobs.length} documents · template “{batch.template_name}”</div>
            </div>
            <div className="flex gap-2">
              {batch.counts.failed > 0 && <Button icon={<RefreshCw className="h-4 w-4" />} onClick={async () => setBatch(await api(`/api/batches/${batch.id}/retry-failed`, { method: "POST" }))}>Retry failed ({batch.counts.failed})</Button>}
              <Button variant="primary" icon={<FileArchive className="h-4 w-4" />} disabled={!batch.counts.succeeded && !batch.counts.needs_review}
                onClick={() => saveFile(`/api/batches/${batch.id}/zip`, `${batch.name}.zip`).catch((e) => toast("error", errMsg(e)))}>Download all (ZIP)</Button>
              <Button onClick={() => setBatch(null)}>New batch</Button>
            </div>
          </div>
          <div className="flex items-center gap-3 mb-5">
            <Progress value={batch.progress} tone={batch.finished ? (batch.counts.failed ? "amber" : "green") : "blue"} />
            <span className="text-sm tabular-nums text-slate-600 w-12 text-right">{Math.round(batch.progress * 100)}%</span>
          </div>
          <div className="flex gap-2 mb-4">
            <Badge tone="green">{batch.counts.succeeded} done</Badge>
            <Badge tone="amber">{batch.counts.needs_review} to review</Badge>
            <Badge tone="red">{batch.counts.failed} failed</Badge>
            <Badge tone="blue">{batch.counts.running + batch.counts.queued} in progress</Badge>
          </div>
          <div className="divide-y divide-slate-100">
            {batch.jobs.map((j) => {
              const running = j.steps?.find((s) => s.status === "running");
              return (
                <div key={j.id} className="flex items-center gap-4 py-3">
                  <FileText className="h-5 w-5 text-slate-400" />
                  <div className="w-72 min-w-0"><div className="text-sm font-medium text-navy-900 truncate">{j.source_name}</div><div className="text-xs text-slate-500 truncate">{j.error || running?.label || (j.result?.pages ? `${j.result.pages} pages` : "")}</div></div>
                  <div className="flex-1"><Progress value={j.progress} tone={j.status === "failed" ? "red" : j.status === "needs_review" ? "amber" : j.status === "succeeded" ? "green" : "blue"} /></div>
                  <StatusBadge status={j.status} />
                  <div className="flex gap-1 w-44 justify-end">
                    {j.result?.outputs?.pdf && <Button size="sm" variant="ghost" icon={<Download className="h-3.5 w-3.5" />} onClick={() => saveFile(`/api/jobs/${j.id}/file/pdf`, `${j.title}.pdf`).catch((e) => toast("error", errMsg(e)))}>PDF</Button>}
                    {j.status === "failed" && <Button size="sm" variant="ghost" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={async () => { await api(`/api/jobs/${j.id}/retry`, { method: "POST" }); setBatch(await api(`/api/batches/${batch.id}`)); }}>Retry</Button>}
                    {j.result?.outputs?.pdf && <Button size="sm" variant="ghost" onClick={() => navigate(`editor/${j.document_id}`)}>Open</Button>}
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      )}
      <div className="mt-8">
        <div className="font-semibold text-navy-900 mb-3">Batch history</div>
        {!history.length ? <div className="text-sm text-slate-500">No batches yet.</div> : (
          <Card className="divide-y divide-slate-50">
            {history.map((b) => (
              <button key={b.id} onClick={() => setBatch(b)} className="w-full text-left flex items-center gap-4 px-5 py-3 hover:bg-slate-50">
                <div className="flex-1"><div className="text-sm font-medium text-navy-900">{b.name}</div><div className="text-xs text-slate-500">{fmtDate(b.created)} · {b.template_name}</div></div>
                <Badge tone="green">{b.counts.succeeded}</Badge><Badge tone="amber">{b.counts.needs_review}</Badge><Badge tone="red">{b.counts.failed}</Badge>
                <span className="text-xs text-slate-400 w-20 text-right">{b.jobs.length} files</span>
              </button>
            ))}
          </Card>
        )}
      </div>
      {starting && <div className="fixed inset-0 bg-white/40 flex items-center justify-center"><Spinner className="h-8 w-8" /></div>}
    </div>
  );
}
