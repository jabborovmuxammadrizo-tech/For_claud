import { Check, Download, Eye, FileArchive, FolderOpen, Images, Loader2, PenTool, RefreshCw, Save, X } from "lucide-react";
import { useState } from "react";
import { navigate } from "../App";
import { api, fileUrl, Issue, Job, saveFile, showInFolder, Template } from "../api";
import { PdfViewer } from "./PdfViewer";
import { Badge, Button, Card, cx, errMsg, IssueIcon, Modal, Progress, useDialogs, useToast } from "./ui";

export function JobTimeline({ job }: { job: Job }) {
  const failed = job.status === "failed";
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <div className="text-sm font-semibold text-navy-900">
          {job.status === "queued" ? "Waiting to start…" : job.status === "running" ? "Processing…" : failed ? "Generation failed" : "Completed"}
        </div>
        <div className="text-sm tabular-nums text-slate-500">{Math.round((job.progress || 0) * 100)}%</div>
      </div>
      <Progress value={job.progress || 0} tone={failed ? "red" : job.status === "needs_review" ? "amber" : job.status === "succeeded" ? "green" : "blue"} />
      <ol className="mt-6 space-y-1">
        {job.steps.map((s, i) => (
          <li key={s.key} className={cx("flex gap-4 rounded-lg px-3 py-2.5", s.status === "running" && "bg-royal-50/70")}>
            <div className={cx("mt-0.5 h-7 w-7 shrink-0 rounded-full flex items-center justify-center text-xs font-bold",
              s.status === "done" ? "bg-emerald-500 text-white" : s.status === "running" ? "bg-royal-600 text-white" :
                s.status === "failed" ? "bg-brandred-600 text-white" : "bg-slate-100 text-slate-400")}>
              {s.status === "done" ? <Check className="h-4 w-4" /> : s.status === "running" ? <Loader2 className="h-4 w-4 animate-spin" /> :
                s.status === "failed" ? <X className="h-4 w-4" /> : i + 1}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-3">
                <div className={cx("text-sm font-medium", s.status === "pending" ? "text-slate-400" : "text-navy-900")}>{s.label}</div>
                {s.status === "running" && <div className="text-xs tabular-nums text-royal-700">{Math.round(s.progress * 100)}%</div>}
                {s.finished && s.started && s.status === "done" && <div className="text-[11px] text-slate-400 tabular-nums">{(s.finished - s.started).toFixed(1)}s</div>}
              </div>
              {s.detail && <div className={cx("text-xs mt-0.5 truncate", s.status === "failed" ? "text-brandred-700" : "text-slate-500")} title={s.detail}>{s.detail}</div>}
              {s.status === "running" && <Progress value={s.progress} className="mt-1.5 h-1" />}
            </div>
          </li>
        ))}
      </ol>
      {failed && job.error && <div className="mt-4 rounded-lg bg-brandred-50 border border-brandred-100 px-4 py-3 text-sm text-brandred-700">{job.error}</div>}
    </div>
  );
}

export function IssueList({ issues, onOpen, max = 50 }: { issues: Issue[]; onOpen?: (i: Issue) => void; max?: number }) {
  const [all, setAll] = useState(false);
  if (!issues.length) return <div className="text-sm text-emerald-700 flex items-center gap-2"><Check className="h-4 w-4" />No problems found.</div>;
  const shown = all ? issues : issues.slice(0, max);
  return (
    <div className="space-y-1.5">
      {shown.map((i, k) => (
        <div key={k} className={cx("flex items-start gap-2.5 rounded-lg px-3 py-2 text-[13px]",
          i.level === "critical" ? "bg-brandred-50/70" : i.level === "warning" ? "bg-amber-50/70" : "bg-slate-50")}>
          <IssueIcon level={i.level} className="mt-0.5" />
          <div className="flex-1 text-slate-700 leading-snug">{i.message}{i.page ? <span className="text-slate-400"> · page {i.page}</span> : null}</div>
          {onOpen && (i.block || i.page) && <button className="text-xs text-royal-700 hover:underline shrink-0" onClick={() => onOpen(i)}>Show</button>}
        </div>
      ))}
      {issues.length > max && !all && <button className="text-xs text-royal-700 hover:underline" onClick={() => setAll(true)}>Show all {issues.length}</button>}
    </div>
  );
}

export function ResultPanel({ job, onRegenerate, templates }: { job: Job; onRegenerate: () => void; templates?: Template[] }) {
  const toast = useToast();
  const { prompt } = useDialogs();
  const [preview, setPreview] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const r = job.result!;
  const v = r.validation!;
  const title = r.title || "document";
  const name = (s: string) => `${title.replace(/[\\/:*?"<>|]+/g, "_")}${s}`;
  const act = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    try { await fn(); } catch (e) { toast("error", errMsg(e)); } finally { setBusy(null); }
  };
  const saveAsTemplate = () => act("tpl", async () => {
    const base = templates?.find((t) => t.id === job.template_id);
    const n = await prompt({ title: "Save as new template", label: "Template name", initial: `${base?.name || "Template"} — ${title}`.slice(0, 80), confirmText: "Save template" });
    if (!n) return;
    await api(`/api/templates/${job.template_id}/duplicate`, { body: { name: n } });
    toast("success", `Template “${n}” saved. You can now select it for future documents.`);
  });
  const pageImages = () => act("img", async () => {
    const recs = await api<{ id: string; path: string }[]>(`/api/documents/${job.document_id}/export`, { body: { template_id: job.template_id, kind: "png", dpi: 150 } });
    const saved = await saveFile(`/api/exports/${recs[0].id}/file`, name(" pages (PNG).zip"));
    if (saved) toast("success", "Page images saved.");
  });
  const s = v.summary;
  return (
    <div className="space-y-5">
      <Card className={cx("p-6 border-l-4", s.passed ? "border-l-emerald-500" : "border-l-amber-500")}>
        <div className="flex items-start gap-4">
          <div className={cx("h-12 w-12 rounded-xl flex items-center justify-center", s.passed ? "bg-emerald-50 text-emerald-600" : "bg-amber-50 text-amber-600")}>
            {s.passed ? <Check className="h-7 w-7" /> : <IssueIcon level="warning" className="h-7 w-7" />}
          </div>
          <div className="flex-1">
            <div className="text-lg font-bold text-navy-900">{s.passed ? "Your PDF is ready" : "PDF created — please review the notes below"}</div>
            <div className="text-sm text-slate-500 mt-0.5">
              {r.pages} pages · template “{r.template_name}” · {r.counts?.questions ?? "—"} questions, {r.counts?.options ?? "—"} answer options, {r.counts?.images ?? 0} images, {r.counts?.tables ?? 0} tables
            </div>
            <div className="flex gap-2 mt-2">
              <Badge tone={s.critical ? "red" : "green"}>{s.critical} critical</Badge>
              <Badge tone={s.warning ? "amber" : "slate"}>{s.warning} warnings</Badge>
              <Badge tone="slate">{s.info} notes</Badge>
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-2 mt-5">
          <Button variant="primary" icon={<Download className="h-4 w-4" />} loading={busy === "dl"}
            onClick={() => act("dl", async () => { const p = await saveFile(`/api/jobs/${job.id}/file/pdf`, name(".pdf")); if (p) toast("success", `Saved to ${p}`); })}>Download PDF</Button>
          <Button icon={<Eye className="h-4 w-4" />} onClick={() => setPreview(true)}>Preview document</Button>
          <Button icon={<PenTool className="h-4 w-4" />} onClick={() => navigate(`editor/${job.document_id}?template=${job.template_id}`)}>Open in editor</Button>
          <Button icon={<RefreshCw className="h-4 w-4" />} onClick={onRegenerate}>Regenerate</Button>
          <Button icon={<Save className="h-4 w-4" />} loading={busy === "tpl"} onClick={saveAsTemplate}>Save as template</Button>
          {r.outputs?.compressed && <Button icon={<FileArchive className="h-4 w-4" />} loading={busy === "cmp"}
            onClick={() => act("cmp", () => saveFile(`/api/jobs/${job.id}/file/compressed`, name(" (compressed).pdf")))}>Compressed PDF</Button>}
          <Button icon={<Images className="h-4 w-4" />} loading={busy === "img"} onClick={pageImages}>Export page images</Button>
          {window.ptd && r.export_dir && <Button variant="ghost" icon={<FolderOpen className="h-4 w-4" />} onClick={() => showInFolder(r.outputs!.pdf)}>Show in folder</Button>}
        </div>
      </Card>
      {!!r.thumbnails?.length && (
        <div className="flex gap-3 overflow-x-auto pb-2">
          {r.thumbnails.map((_, i) => (
            <button key={i} onClick={() => setPreview(true)} className="shrink-0 rounded-lg border border-slate-200 bg-white p-1 hover:border-royal-400 hover:shadow-card transition">
              <img src={fileUrl(`/api/jobs/${job.id}/thumb/${i + 1}`)} alt={`Page ${i + 1}`} className="h-40 rounded" loading="lazy" />
              <div className="text-[10px] text-slate-500 text-center mt-0.5">{i + 1}</div>
            </button>
          ))}
        </div>
      )}
      <Card className="p-5">
        <div className="font-semibold text-navy-900 mb-3">Quality check</div>
        <IssueList issues={v.issues} onOpen={(i) => navigate(`editor/${job.document_id}?template=${job.template_id}${i.block ? `&block=${i.block}` : ""}${i.page ? `&page=${i.page}` : ""}`)} />
      </Card>
      <Modal open={preview} onClose={() => setPreview(false)} title={`Preview — ${title}`} width="max-w-[1200px]">
        <div className="h-[78vh]"><PdfViewer url={fileUrl(`/api/jobs/${job.id}/file/pdf`)} /></div>
      </Modal>
    </div>
  );
}

export function LogTail({ job }: { job: Job }) {
  if (!job.log?.length) return null;
  return (
    <div className="mt-4 rounded-lg bg-navy-950 text-[11.5px] font-mono text-slate-300 p-3 max-h-40 overflow-auto">
      {job.log.slice(-14).map((l, i) => (
        <div key={i} className={cx(l.level === "error" ? "text-red-300" : l.level === "warning" ? "text-amber-200" : "")}>
          <span className="text-slate-500">{new Date(l.ts * 1000).toLocaleTimeString()} </span>{l.message.split("\n")[0]}
        </div>
      ))}
    </div>
  );
}
