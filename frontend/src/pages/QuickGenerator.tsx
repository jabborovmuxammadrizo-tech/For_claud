import { FileText, RotateCcw, Sparkles, Star, Zap } from "lucide-react";
import { useEffect, useState } from "react";
import type { Route } from "../App";
import { api, Doc, Issue, Job, pollJob, Template, upload } from "../api";
import { JobTimeline, LogTail, ResultPanel } from "../components/job";
import { Badge, Button, Card, cx, Dropzone, errMsg, IssueIcon, Progress, SectionTitle, Spinner, useToast } from "../components/ui";

export const ACCEPT = ".pdf,.docx,.txt,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp";
type Rec = { template_id: string; name: string; score: number; reasons: string[] };

export function TemplateCard({ t, selected, onSelect, rec }: { t: Template; selected: boolean; onSelect: () => void; rec?: Rec }) {
  const c = t.config.branding.colors;
  return (
    <button onClick={onSelect} className={cx("text-left rounded-xl border-2 bg-white p-4 transition-all hover:shadow-card",
      selected ? "border-royal-600 shadow-card ring-4 ring-royal-100" : "border-slate-200 hover:border-slate-300")}>
      <div className="flex items-center gap-1.5 mb-3">
        {[c.secondary, c.primary, c.accent].map((col: string, i: number) => <span key={i} className="h-5 w-5 rounded-md border border-black/5" style={{ background: col }} />)}
        <div className="flex-1" />
        {!!t.is_default && <Badge tone="navy"><Star className="h-3 w-3" />Default</Badge>}
        {rec && rec.score > 0 && <Badge tone="green"><Sparkles className="h-3 w-3" />Recommended</Badge>}
      </div>
      <div className="font-semibold text-navy-900 text-[14px] leading-snug">{t.name}</div>
      <div className="text-xs text-slate-500 mt-1 line-clamp-2">{t.description || t.category}</div>
      <div className="text-[11px] text-slate-400 mt-2">{t.config.fonts.body} · {t.config.pagination.density} · {t.config.page.columns === 2 ? "2 columns" : "1 column"}{t.config.cover.enabled ? " · cover" : ""}</div>
      {rec && rec.score > 0 && rec.reasons.length > 0 && <div className="text-[11px] text-emerald-700 mt-1.5">{rec.reasons.join(" · ")}</div>}
    </button>
  );
}

export default function QuickGenerator({ route }: { route: Route }) {
  const toast = useToast();
  const [templates, setTemplates] = useState<Template[]>([]);
  const [tid, setTid] = useState<string>("");
  const [file, setFile] = useState<File | null>(null);
  const [doc, setDoc] = useState<Doc | null>(null);
  const [extract, setExtract] = useState<Job | null>(null);
  const [recs, setRecs] = useState<Rec[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    api<Template[]>("/api/templates").then((t) => {
      setTemplates(t);
      const pre = route.params.get("template");
      setTid(pre && t.some((x) => x.id === pre) ? pre : (t.find((x) => x.is_default) || t[0])?.id || "");
    });
  }, [route.params]);

  const onFile = async (files: File[]) => {
    const f = files[0];
    setFile(f); setDoc(null); setExtract(null); setRecs([]); setJob(null);
    setUploading(true);
    try {
      const settings = await api("/api/settings");
      const r = await upload("/api/documents", { import_mode: settings.default_import_mode || "editable", extract: "true" }, [f]);
      setDoc(r.document);
      const done = await pollJob(r.job.id, setExtract);
      if (done.status === "succeeded") {
        setRecs(await api<Rec[]>(`/api/documents/${r.document.id}/recommend`));
      } else {
        toast("error", done.error || "The document could not be read.");
      }
    } catch (e) {
      toast("error", errMsg(e));
      setFile(null);
    } finally {
      setUploading(false);
    }
  };

  const generate = async (force = false) => {
    if (!doc || !tid) return;
    try {
      const j = await api<Job>("/api/generate", { body: { document_id: doc.id, template_id: tid, options: force ? { force: true } : {} } });
      setJob(j);
      const done = await pollJob(j.id, setJob);
      if (done.status === "failed") toast("error", done.error || "Generation failed");
    } catch (e) { toast("error", errMsg(e)); }
  };

  const reset = () => { setFile(null); setDoc(null); setExtract(null); setRecs([]); setJob(null); };
  const extracting = !!file && (!extract || ["queued", "running"].includes(extract.status));
  const ready = !!doc && extract?.status === "succeeded";
  const recMap = Object.fromEntries(recs.map((r) => [r.template_id, r]));
  const sortedTemplates = [...templates].sort((a, b) => (recMap[b.id]?.score || 0) - (recMap[a.id]?.score || 0) || b.is_default - a.is_default);
  const warnings: Issue[] = (extract?.result?.warnings || []).filter((w) => w.level !== "info");

  if (job) {
    const finished = !["queued", "running"].includes(job.status);
    return (
      <div className="max-w-5xl mx-auto">
        <SectionTitle title={finished ? (job.status === "failed" ? "Generation failed" : "Generation complete") : "Generating your PDF…"}
          subtitle={`${file?.name || doc?.source_name} → ${templates.find((t) => t.id === job.template_id)?.name || ""}${job.reused ? " (identical result reused)" : ""}`}
          actions={finished && <Button icon={<RotateCcw className="h-4 w-4" />} onClick={reset}>New document</Button>} />
        {(!finished || job.status === "failed") && (
          <Card className="p-6">
            <JobTimeline job={job} />
            <LogTail job={job} />
            {job.status === "failed" && <div className="flex gap-2 mt-5"><Button variant="primary" onClick={() => generate(true)}>Retry</Button><Button onClick={reset}>Start over</Button></div>}
          </Card>
        )}
        {finished && job.status !== "failed" && job.result && <ResultPanel job={job} templates={templates} onRegenerate={() => generate(true)} />}
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto">
      <SectionTitle title="Quick Generator" subtitle="Upload an examination, choose a saved template and click one button. Everything else is automatic." />
      <div className="grid grid-cols-1 gap-6">
        <Card className="p-6">
          <StepHead n={1} title="Upload your document" done={!!file} />
          {!file ? (
            <Dropzone accept={ACCEPT} onFiles={onFile} title="Select PDF / DOCX" subtitle="or drag and drop · PDF, DOCX, TXT, PNG, JPG, TIFF" />
          ) : (
            <div className="rounded-xl border border-slate-200 p-4 flex items-start gap-4">
              <div className="h-11 w-11 rounded-lg bg-royal-50 text-royal-600 flex items-center justify-center"><FileText className="h-6 w-6" /></div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-3">
                  <div className="font-medium text-navy-900 truncate">{file.name}</div>
                  <button className="text-xs text-slate-500 hover:text-brandred-600" onClick={reset} disabled={uploading}>Remove</button>
                </div>
                {extracting && (
                  <div className="mt-2">
                    <div className="text-xs text-slate-500 mb-1">{uploading && !extract ? "Uploading…" : extract?.steps.find((s) => s.status === "running")?.detail || "Analyzing document…"}</div>
                    <Progress value={extract?.progress || 0.03} />
                  </div>
                )}
                {ready && extract?.result?.stats && (
                  <div className="flex flex-wrap gap-2 mt-2">
                    <Badge tone="blue">{extract.result.stats.questions} questions</Badge>
                    <Badge tone="slate">{extract.result.stats.options} options</Badge>
                    <Badge tone="slate">{extract.result.stats.images} images</Badge>
                    <Badge tone="slate">{extract.result.stats.tables} tables</Badge>
                    <Badge tone="slate">{extract.result.stats.words} words</Badge>
                  </div>
                )}
                {extract?.status === "failed" && <div className="text-sm text-brandred-700 mt-2">{extract.error}</div>}
                {warnings.length > 0 && (
                  <div className="mt-3 space-y-1">
                    {warnings.map((w, i) => <div key={i} className="flex gap-2 text-xs text-amber-800 bg-amber-50 rounded-md px-2.5 py-1.5"><IssueIcon level={w.level} />{w.message}</div>)}
                  </div>
                )}
              </div>
            </div>
          )}
        </Card>

        <Card className="p-6">
          <StepHead n={2} title="Choose saved template" done={!!tid} />
          {!templates.length ? <Spinner /> : (
            <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
              {sortedTemplates.map((t) => <TemplateCard key={t.id} t={t} selected={tid === t.id} onSelect={() => setTid(t.id)} rec={recMap[t.id]} />)}
            </div>
          )}
          {recs.length > 0 && recs[0].score > 0 && recs[0].template_id !== tid && (
            <div className="text-xs text-slate-500 mt-3"><Sparkles className="inline h-3.5 w-3.5 text-emerald-600" /> Suggestion: “{recs[0].name}” may suit this document. Your selection is kept unless you change it.</div>
          )}
        </Card>

        <Card className="p-6 flex items-center justify-between gap-6 bg-gradient-to-r from-white to-royal-50/60">
          <div>
            <StepHead n={3} title="One-click generate" done={false} noMargin />
            <div className="text-sm text-slate-500 mt-1 ml-10">Analysis, template, layout, quality check and final PDF — fully automatic.</div>
          </div>
          <Button variant="hero" size="lg" icon={<Zap className="h-5 w-5" />} disabled={!ready || !tid} onClick={() => generate(false)}>
            {extracting ? "Analyzing document…" : "ONE-CLICK GENERATE"}
          </Button>
        </Card>
      </div>
    </div>
  );
}

function StepHead({ n, title, done, noMargin }: { n: number; title: string; done: boolean; noMargin?: boolean }) {
  return (
    <div className={cx("flex items-center gap-3", !noMargin && "mb-4")}>
      <div className={cx("h-7 w-7 rounded-full flex items-center justify-center text-sm font-bold", done ? "bg-emerald-500 text-white" : "bg-navy-900 text-white")}>{n}</div>
      <div className="font-semibold text-navy-900 uppercase tracking-wide text-[13px]">{title}</div>
    </div>
  );
}

