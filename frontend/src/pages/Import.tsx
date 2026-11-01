import { ArrowLeft, ArrowRight, Eye, EyeOff, FileText, Layers, PenTool, RotateCw, Zap } from "lucide-react";
import React, { useState } from "react";
import { navigate, Route } from "../App";
import { api, Doc, DocModel, fileUrl, Job, pollJob, upload } from "../api";
import { IssueList, JobTimeline } from "../components/job";
import { Badge, Button, Card, cx, Dropzone, errMsg, SectionTitle, useToast } from "../components/ui";
import { ACCEPT } from "./QuickGenerator";

export default function ImportPage(_: { route: Route }) {
  const toast = useToast();
  const [mode, setMode] = useState<"editable" | "original">("editable");
  const [doc, setDoc] = useState<Doc | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [model, setModel] = useState<DocModel | null>(null);
  const [saving, setSaving] = useState(false);

  const onFile = async (f: File[]) => {
    setDoc(null); setJob(null); setModel(null);
    try {
      const r = await upload("/api/documents", { import_mode: mode, extract: "true" }, f);
      setDoc(r.document);
      const done = await pollJob(r.job.id, setJob);
      if (done.status === "succeeded") setModel(await api<DocModel>(`/api/documents/${r.document.id}/model`));
    } catch (e) { toast("error", errMsg(e)); }
  };

  const pages = model?.original_pages || null;
  const setPages = (p: NonNullable<DocModel["original_pages"]>) => setModel((m) => (m ? { ...m, original_pages: p } : m));
  const move = (i: number, d: number) => {
    if (!pages) return;
    const j = i + d;
    if (j < 0 || j >= pages.length) return;
    const n = [...pages];
    [n[i], n[j]] = [n[j], n[i]];
    setPages(n);
  };
  const savePages = async () => {
    if (!doc || !model) return;
    setSaving(true);
    try { await api(`/api/documents/${doc.id}/model`, { method: "PUT", body: { model, note: "Page order changed" } }); toast("success", "Page arrangement saved. The original file is unchanged."); }
    catch (e) { toast("error", errMsg(e)); } finally { setSaving(false); }
  };
  const stats = job?.result?.stats;
  const showThumbs = doc && ["pdf", "image"].includes(doc.kind) && job?.status === "succeeded";
  const nThumbs = model?.meta?.source_pages || (pages ? pages.length : 0);

  return (
    <div>
      <SectionTitle title="PDF Import" subtitle="Import a PDF, Word document, text file or scanned image. The original file is always kept unchanged." />
      <div className="grid grid-cols-2 gap-4 mb-6">
        {([["editable", "Mode A — Editable import", "Converts the document into editable questions, options, text, tables and images. Best for re-designing with templates.", PenTool],
          ["original", "Mode B — Original page import", "Keeps each original page exactly as it is (as a background) and adds your branding, header, footer and new elements on top.", Layers]] as const).map(([k, t, d, Icon]) => (
          <button key={k} onClick={() => setMode(k)} className={cx("text-left rounded-xl border-2 p-5 bg-white transition", mode === k ? "border-royal-600 ring-4 ring-royal-100" : "border-slate-200 hover:border-slate-300")}>
            <div className="flex items-center gap-3"><Icon className="h-5 w-5 text-royal-600" /><div className="font-semibold text-navy-900">{t}</div></div>
            <div className="text-sm text-slate-500 mt-2">{d}</div>
          </button>
        ))}
      </div>
      {!doc && <Card className="p-6"><Dropzone accept={ACCEPT} onFiles={onFile} title="Select a document to import" subtitle="PDF, DOCX, TXT, PNG, JPG, TIFF · up to 300 MB" /></Card>}
      {doc && job && (
        <div className="grid grid-cols-3 gap-6">
          <Card className="p-6 col-span-1">
            <div className="flex items-center gap-3 mb-4"><FileText className="h-5 w-5 text-royal-600" /><div className="font-semibold text-navy-900 truncate">{doc.source_name}</div></div>
            <JobTimeline job={job} />
            {stats && (
              <div className="grid grid-cols-2 gap-2 mt-5 text-sm">
                {Object.entries({ Questions: stats.questions, Options: stats.options, Sections: stats.headings, Paragraphs: stats.paragraphs, Tables: stats.tables, Images: stats.images }).map(([k, v]) => (
                  <div key={k} className="rounded-lg bg-slate-50 px-3 py-2"><div className="text-lg font-bold text-navy-900 tabular-nums">{v}</div><div className="text-xs text-slate-500">{k}</div></div>
                ))}
              </div>
            )}
            {job.status === "succeeded" && (
              <div className="flex flex-col gap-2 mt-5">
                <Button variant="primary" icon={<PenTool className="h-4 w-4" />} onClick={() => navigate(`editor/${doc.id}`)}>Open in editor</Button>
                <Button icon={<Zap className="h-4 w-4" />} onClick={() => navigate(`editor/${doc.id}?generate=1`)}>Generate PDF</Button>
                <Button variant="ghost" onClick={() => { setDoc(null); setJob(null); setModel(null); }}>Import another file</Button>
              </div>
            )}
          </Card>
          <div className="col-span-2 space-y-6">
            {job.result?.warnings && (
              <Card className="p-5">
                <div className="font-semibold text-navy-900 mb-3">Extraction report</div>
                <IssueList issues={job.result.warnings} />
                {!!model?.meta?.scanned_pages?.length && <div className="text-xs text-slate-500 mt-3">Scanned pages cannot be converted perfectly. Check OCR text in the editor before printing.</div>}
              </Card>
            )}
            {showThumbs && (
              <Card className="p-5">
                <div className="flex items-center justify-between mb-3">
                  <div className="font-semibold text-navy-900">{pages ? "Original pages — arrange, rotate or exclude" : "Original pages"}</div>
                  {pages && <Button size="sm" variant="primary" loading={saving} onClick={savePages}>Save page arrangement</Button>}
                </div>
                <div className="grid grid-cols-4 xl:grid-cols-6 gap-3">
                  {(pages || Array.from({ length: nThumbs }, (_, i) => ({ index: i, rotation: 0, include: true }))).map((p, i) => (
                    <div key={`${p.index}-${i}`} className={cx("rounded-lg border p-1.5 bg-white", p.include ? "border-slate-200" : "border-dashed border-slate-300 opacity-50")}>
                      <div className="aspect-[1/1.41] bg-slate-50 flex items-center justify-center overflow-hidden rounded">
                        <img src={fileUrl(`/api/documents/${doc.id}/original/pages/${p.index + 1}.png?dpi=50`)} alt={`Page ${p.index + 1}`}
                          style={{ transform: `rotate(${p.rotation}deg)` }} className="max-h-full max-w-full transition-transform" loading="lazy" />
                      </div>
                      <div className="flex items-center justify-between mt-1.5">
                        <span className="text-[11px] text-slate-500">#{p.index + 1}{p.rotation ? ` · ${p.rotation}°` : ""}</span>
                        {pages && (
                          <div className="flex gap-0.5">
                            <IconBtn label="Move left" onClick={() => move(i, -1)}><ArrowLeft className="h-3.5 w-3.5" /></IconBtn>
                            <IconBtn label="Move right" onClick={() => move(i, 1)}><ArrowRight className="h-3.5 w-3.5" /></IconBtn>
                            <IconBtn label="Rotate 90°" onClick={() => setPages(pages.map((x, k) => (k === i ? { ...x, rotation: (x.rotation + 90) % 360 } : x)))}><RotateCw className="h-3.5 w-3.5" /></IconBtn>
                            <IconBtn label={p.include ? "Exclude page" : "Include page"} onClick={() => setPages(pages.map((x, k) => (k === i ? { ...x, include: !x.include } : x)))}>{p.include ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}</IconBtn>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
                {pages && <div className="text-xs text-slate-500 mt-3"><Badge tone="blue">Mode B</Badge> Page changes apply to generated PDFs only; the uploaded original is never modified.</div>}
              </Card>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function IconBtn({ children, onClick, label }: { children: React.ReactNode; onClick: () => void; label: string }) {
  return <button title={label} aria-label={label} onClick={onClick} className="p-1 rounded hover:bg-slate-100 text-slate-500 hover:text-navy-900">{children}</button>;
}
