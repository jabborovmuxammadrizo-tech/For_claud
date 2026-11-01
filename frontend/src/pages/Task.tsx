import { CheckCircle2, FileText, FolderOpen, Info, Loader2, Square, XCircle, Zap } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Route } from "../App";
import { api, Issue, Job, openPath, showInFolder, Template } from "../api";
import { IssueList } from "../components/job";
import { Badge, Button, Card, cx, errMsg, Progress, Spinner } from "../components/ui";
import { TemplateCard } from "./QuickGenerator";

type Req = { id: string; command: string; paths: string[]; pick: boolean };
type TaskJob = { id: string; kind: string; status: Job["status"] | "cancelled"; progress: number; error: string | null; source_name: string; title: string; steps: Job["steps"]; result: any; document_id: string | null };
type Task = { id: string; name: string; jobs: TaskJob[]; progress: number; counts: Record<string, number>; finished: boolean; template_name: string };

const TITLES: Record<string, string> = {
  "generate-default": "Generate PDF (default template)", "generate-template": "Generate PDF", "batch-generate": "Batch generate",
  open: "Open in PDF Test Designer", edit: "Edit document", "open-folder": "Open folder", extract: "Extract text and images",
  "convert-editable": "Convert to editable document", "convert-pdf": "Convert to PDF", compress: "Compress PDF", grayscale: "Convert to grayscale",
  info: "Document information", "image-library": "Add to Image Library", "image-pdf": "Create PDF from image", "image-editor": "Open in Image Editor",
  "image-background": "Use as document background", "image-watermark": "Use as watermark",
};
const base = (p: string) => p.split(/[\\/]/).pop() || p;

export default function TaskPage({ route }: { route: Route }) {
  const [req, setReq] = useState<Req | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [tid, setTid] = useState("");
  const [phase, setPhase] = useState<"loading" | "pick" | "running" | "done" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [task, setTask] = useState<Task | null>(null);
  const [outDir, setOutDir] = useState<string | null>(null);
  const [skipped, setSkipped] = useState<{ path: string; reason: string }[]>([]);
  const [report, setReport] = useState(false);
  const notified = useRef(false);
  const settings = useRef<any>({});

  useEffect(() => {
    (async () => {
      settings.current = await api("/api/settings");
      let r: Req | null = null;
      if (window.ptd) r = (await window.ptd.shellRequest(route.id || "")) as Req | null;
      else { const q = route.params; r = { id: "test", command: q.get("cmd") || "generate-default", paths: JSON.parse(q.get("paths") || "[]"), pick: q.get("pick") === "1" }; }
      if (!r) { setError("This request has expired. Run the action again from File Explorer."); setPhase("error"); return; }
      setReq(r);
      document.title = `PDF Test Designer — ${TITLES[r.command] || r.command}`;
      if (r.pick) {
        const t = await api<Template[]>("/api/templates");
        setTemplates(t);
        const def = settings.current.shell_default_template;
        setTid((t.find((x) => x.id === def) || t.find((x) => x.is_default) || t[0]).id);
        setPhase("pick");
      } else {
        start(r, null);
      }
    })().catch((e) => { setError(errMsg(e)); setPhase("error"); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const notify = (title: string, body: string, open?: string) => {
    if (notified.current || settings.current.shell_notifications === false) return;
    notified.current = true;
    window.ptd?.notify(title, body, open);
  };

  const start = async (r: Req, templateId: string | null) => {
    setPhase("running");
    try {
      const cmd = r.command === "generate-template" ? "generate-template" : r.command;
      const res = await api("/api/shell/run", { body: { command: cmd, paths: r.paths, template_id: templateId } });
      setSkipped(res.skipped || []);
      if (res.kind === "open") {
        for (const j of res.jobs) {
          for (;;) { const s = await api<Job>(`/api/jobs/${j}`); if (!["queued", "running"].includes(s.status)) break; await new Promise((x) => setTimeout(x, 400)); }
        }
        await window.ptd?.openMain(res.documents.length === 1 && r.command !== "open-folder" ? `editor/${res.documents[0]}` : "documents");
        setMessage(`${res.documents.length} document(s) opened in PDF Test Designer.`);
        setPhase("done");
        setTimeout(() => window.close(), 1200);
        return;
      }
      if (res.kind === "immediate") {
        setMessage(res.message);
        setPhase("done");
        if (r.command === "image-editor") await window.ptd?.openMain("images");
        notify("PDF Test Designer", res.message);
        return;
      }
      setOutDir(res.output_dir);
      poll(res.task_id);
    } catch (e) {
      const m = errMsg(e);
      setError(m);
      setPhase("error");
      notify("PDF Test Designer — action failed", m);
    }
  };

  const poll = async (id: string) => {
    for (;;) {
      const t = await api<Task>(`/api/batches/${id}`);
      setTask(t);
      if (t.finished) { finish(t); return; }
      await new Promise((x) => setTimeout(x, 600));
    }
  };

  const finish = (t: Task) => {
    setPhase("done");
    const ok = t.jobs.filter((j) => j.status === "succeeded" || j.status === "needs_review");
    const review = t.jobs.filter((j) => j.status === "needs_review" || (j.result?.validation?.issues || []).some((i: Issue) => i.code === "scanned_source" || i.code === "ocr_used"));
    const delivered = ok.map((j) => j.result?.outputs?.delivered || j.result?.delivered?.[0]).filter(Boolean) as string[];
    let title: string, body: string;
    if (t.jobs.length === 1) {
      title = ok.length ? "Completed successfully" : t.jobs[0].status === "cancelled" ? "Cancelled" : "Processing failed";
      body = ok.length ? `${base(delivered[0] || t.jobs[0].source_name)} is ready.` : t.jobs[0].error || "";
    } else {
      title = `${ok.length} of ${t.jobs.length} documents processed`;
      body = t.counts.failed ? `${t.counts.failed} failed — see the processing report.` : "All documents are ready.";
    }
    if (review.length) body += ` ${review.length} document(s) require manual review (OCR / quality notes).`;
    notify(`PDF Test Designer — ${title}`, body, delivered.length === 1 ? delivered[0] : outDir || undefined);
    if (t.jobs.length > 1 && settings.current.output_zip && ok.length) api(`/api/batches/${t.id}/zip?to_output=true`).catch(() => {});
  };

  const cancel = async () => { if (task) setTask(await api(`/api/batches/${task.id}/cancel`, { method: "POST" })); };

  if (phase === "loading") return <div className="h-screen flex items-center justify-center"><Spinner className="h-8 w-8" /></div>;
  const delivered = (task?.jobs || []).map((j) => j.result?.outputs?.delivered || j.result?.delivered?.[0]).filter(Boolean) as string[];
  const info = task?.jobs[0]?.result?.info;
  return (
    <div className="min-h-screen bg-slate-50 p-5">
      <div className="flex items-center gap-3 mb-4">
        <img src="./logo.svg" alt="" className="h-9 w-9" />
        <div className="min-w-0">
          <div className="font-bold text-navy-900">{req ? TITLES[req.command] || req.command : "PDF Test Designer"}</div>
          <div className="text-xs text-slate-500 truncate">{req ? (req.paths.length === 1 ? base(req.paths[0]) : `${req.paths.length} items selected`) : ""}</div>
        </div>
      </div>

      {phase === "pick" && (
        <Card className="p-4">
          <div className="font-semibold text-navy-900 text-sm mb-3">Choose a saved template</div>
          <div className="grid grid-cols-2 gap-2 max-h-[440px] overflow-auto pr-1">
            {templates.map((t) => <TemplateCard key={t.id} t={t} selected={tid === t.id} onSelect={() => setTid(t.id)} />)}
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <Button onClick={() => window.close()}>Cancel</Button>
            <Button variant="primary" icon={<Zap className="h-4 w-4" />} onClick={() => req && start(req, tid)}>Generate</Button>
          </div>
        </Card>
      )}

      {phase === "error" && (
        <Card className="p-5 border-l-4 border-l-brandred-600">
          <div className="flex gap-3"><XCircle className="h-6 w-6 text-brandred-600 shrink-0" /><div><div className="font-semibold text-navy-900">The action could not be completed</div><div className="text-sm text-slate-600 mt-1">{error}</div></div></div>
          <div className="flex justify-end gap-2 mt-4"><Button onClick={() => window.ptd?.openMain("settings")}>Open settings</Button><Button variant="primary" onClick={() => window.close()}>Close</Button></div>
        </Card>
      )}

      {message && phase === "done" && !task && (
        <Card className="p-5"><div className="flex gap-3"><CheckCircle2 className="h-6 w-6 text-emerald-500 shrink-0" /><div className="text-sm text-slate-700">{message}</div></div>
          <div className="flex justify-end mt-4"><Button variant="primary" onClick={() => window.close()}>Close</Button></div></Card>
      )}

      {phase === "running" && !task && <Card className="p-6 flex items-center gap-3 text-sm text-slate-600"><Loader2 className="h-5 w-5 animate-spin text-royal-600" />Starting…</Card>}

      {task && (
        <Card className="p-4">
          <div className="flex items-center justify-between mb-2">
            <div className="text-sm font-semibold text-navy-900">{task.finished ? "Finished" : "Processing…"}</div>
            <div className="text-xs tabular-nums text-slate-500">{Math.round(task.progress * 100)}%</div>
          </div>
          <Progress value={task.progress} tone={task.finished ? (task.counts.failed ? "amber" : "green") : "blue"} />
          {task.template_name && ["generate-default", "generate-template", "batch-generate"].includes(req?.command || "") && <div className="text-[11px] text-slate-400 mt-1.5">Template: {task.template_name}</div>}
          <div className="mt-3 divide-y divide-slate-100 max-h-[300px] overflow-auto">
            {task.jobs.map((j) => {
              const running = j.steps?.find((s) => s.status === "running");
              return (
                <div key={j.id} className="flex items-center gap-3 py-2">
                  {j.status === "succeeded" ? <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" /> : j.status === "failed" ? <XCircle className="h-4 w-4 text-brandred-600 shrink-0" /> :
                    j.status === "needs_review" ? <Info className="h-4 w-4 text-amber-500 shrink-0" /> : j.status === "cancelled" ? <Square className="h-4 w-4 text-slate-400 shrink-0" /> : <Loader2 className="h-4 w-4 animate-spin text-royal-600 shrink-0" />}
                  <div className="flex-1 min-w-0">
                    <div className="text-[13px] text-navy-900 truncate">{j.source_name}</div>
                    <div className={cx("text-[11px] truncate", j.status === "failed" ? "text-brandred-700" : "text-slate-500")}>
                      {j.error || running?.detail || running?.label || (j.status === "needs_review" ? "Created — please review the quality notes" : j.status === "succeeded" ? base(j.result?.outputs?.delivered || j.result?.delivered?.[0] || "") : j.status)}
                    </div>
                  </div>
                  {(j.result?.outputs?.delivered || j.result?.delivered?.[0]) && <button className="text-xs text-royal-700 hover:underline" onClick={() => openPath(j.result?.outputs?.delivered || j.result.delivered[0])}>Open</button>}
                </div>
              );
            })}
          </div>
          {!!skipped.length && <div className="mt-2 text-[11px] text-amber-800 bg-amber-50 rounded-md px-2.5 py-1.5">Skipped: {skipped.map((s) => `${base(s.path)} (${s.reason})`).join("; ")}</div>}
          {info && (
            <table className="w-full text-[12.5px] mt-3">
              <tbody>
                {[["File", info.file], ["Size", `${Math.round(info.size / 1024)} KB`], ["Pages", info.pages], ["Page size", info.page_sizes.join(", ")], ["Images", info.images],
                  ["Text layer", info.scanned ? `Scanned — ${info.pages_without_text} page(s) without text (OCR needed)` : info.pages_without_text ? `${info.pages_without_text} page(s) without text` : "Searchable text on all pages"],
                  ["Fonts", info.fonts.slice(0, 8).join(", ") || "—"], ["Title", info.metadata?.title || "—"], ["Creator", info.metadata?.creator || info.metadata?.producer || "—"], ["Encrypted", info.encrypted ? "Yes" : "No"]]
                  .map(([k, v]) => <tr key={k as string} className="border-b border-slate-50"><td className="py-1 pr-3 text-slate-500 w-28">{k}</td><td className="text-navy-900">{String(v)}</td></tr>)}
              </tbody>
            </table>
          )}
          <div className="flex flex-wrap justify-end gap-2 mt-4">
            {!task.finished && <Button size="sm" onClick={cancel} icon={<Square className="h-3.5 w-3.5" />}>Cancel remaining</Button>}
            {task.finished && delivered.length === 1 && <Button size="sm" variant="primary" icon={<FileText className="h-4 w-4" />} onClick={() => openPath(delivered[0])}>Open generated file</Button>}
            {task.finished && delivered.length > 0 && <Button size="sm" icon={<FolderOpen className="h-4 w-4" />} onClick={() => showInFolder(delivered[0])}>Open output folder</Button>}
            {task.finished && <Button size="sm" variant="ghost" onClick={() => setReport(!report)}>{report ? "Hide" : "View"} processing report</Button>}
            {task.finished && <Button size="sm" variant="ghost" onClick={() => window.close()}>Close</Button>}
          </div>
          {report && (
            <div className="mt-3 space-y-3 max-h-64 overflow-auto">
              {task.jobs.map((j) => (
                <div key={j.id}>
                  <div className="text-xs font-semibold text-navy-900 mb-1 flex items-center gap-2">{j.source_name}<Badge tone={j.status === "succeeded" ? "green" : j.status === "failed" ? "red" : "amber"}>{j.status}</Badge></div>
                  {j.result?.validation ? <IssueList issues={j.result.validation.issues} max={12} /> : j.result?.warnings ? <IssueList issues={j.result.warnings} max={12} /> : <div className="text-xs text-slate-500">{j.error || j.result?.note || "Completed."}</div>}
                </div>
              ))}
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
