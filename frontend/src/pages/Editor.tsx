import {
  AlignCenter, AlignJustify, AlignLeft, AlignRight, ArrowDown, ArrowUp, Bold, ChevronDown, Copy, FileText, GripVertical, Heading, Image as ImageIcon, Italic,
  ListOrdered, Loader2, Minus, PenLine, Plus, Redo2, RotateCw, Save, Scissors, SquareDashed, Table as TableIcon, Trash2, Type, Undo2, Zap,
} from "lucide-react";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { navigate, Route } from "../App";
import { api, Asset, Block, Doc, DocModel, fileUrl, Issue, Job, pollJob, Preview, Template, upload } from "../api";
import { ExportDialog } from "../components/ExportDialog";
import { IssueList, JobTimeline, LogTail, ResultPanel } from "../components/job";
import { PdfPage, usePdf } from "../components/PdfViewer";
import {
  Badge, Button, ColorInput, cx, EmptyState, errMsg, Field, IssueIcon, Modal, NumberInput, Select, Slider, Spinner, TextArea, TextInput, Toggle, useToast,
} from "../components/ui";

const uid = () => "b_" + Math.random().toString(16).slice(2, 18);
const MM = 72 / 25.4;
const QTYPES = [["mcq", "Multiple choice"], ["true_false", "True / False"], ["matching", "Matching"], ["gap_fill", "Gap filling"], ["transformation", "Sentence transformation"],
  ["translation", "Translation"], ["reading", "Reading"], ["listening", "Listening"], ["writing", "Writing task"], ["speaking", "Speaking prompt"], ["open", "Open question"]];
const LAYOUTS = [["standard", "Standard examination page"], ["listening", "Listening page"], ["reading", "Reading page"], ["writing", "Writing page"],
  ["instructions", "Instruction page"], ["answer_sheet", "Answer sheet"], ["results", "Results table"]];

function blockLabel(b: Block, numbers: Record<string, string>): string {
  switch (b.type) {
    case "question": return `${numbers[b.id] ?? b.number ?? "?"}. ${b.text || ""}`;
    case "section": return b.title || "Section";
    case "table": return `Table · ${b.rows?.length || 0} rows`;
    case "image": return `${b.kind === "map" ? "Map" : b.kind === "diagram" ? "Diagram" : "Image"}${b.caption ? ` · ${b.caption}` : ""}`;
    case "answer_space": return `Answer lines · ${b.lines || 3}`;
    case "page_break": return "Page break";
    default: return b.text || b.type;
  }
}
const ICONS: Record<string, React.ElementType> = { question: ListOrdered, section: Heading, heading: Type, instruction: PenLine, paragraph: FileText, table: TableIcon,
  image: ImageIcon, answer_space: Minus, page_break: Scissors };

function newBlock(kind: string): Block {
  const id = uid();
  switch (kind) {
    case "mcq": return { id, type: "question", number: null, number_mode: "auto", qtype: "mcq", text: "New question", options: ["A", "B", "C", "D"].map((l) => ({ label: l, text: "" })), images: [] };
    case "true_false": return { id, type: "question", number: null, number_mode: "auto", qtype: "true_false", text: "New statement", options: [{ label: "A", text: "True" }, { label: "B", text: "False" }], images: [] };
    case "gap_fill": return { id, type: "question", number: null, number_mode: "auto", qtype: "gap_fill", text: "She ______ to school.", options: [], images: [] };
    case "writing": return { id, type: "question", number: null, number_mode: "auto", qtype: "writing", text: "Write about…", options: [], images: [], answer_lines: 8 };
    case "section": return { id, type: "section", title: "New section", layout: "standard" };
    case "heading": return { id, type: "heading", level: 2, text: "Heading" };
    case "instruction": return { id, type: "instruction", text: "Choose the correct answer." };
    case "paragraph": return { id, type: "paragraph", text: "Text" };
    case "table": return { id, type: "table", header_rows: 1, rows: [["Column 1", "Column 2"], ["", ""]] };
    case "answer_space": return { id, type: "answer_space", lines: 4 };
    case "page_break": return { id, type: "page_break" };
    default: return { id, type: "paragraph", text: "" };
  }
}

// ====================================================================== editor
export default function Editor({ route }: { route: Route }) {
  const id = route.id;
  if (!id) return <PickDocument />;
  return <DocumentEditor key={id} id={id} route={route} />;
}

function PickDocument() {
  const [docs, setDocs] = useState<Doc[] | null>(null);
  useEffect(() => { api<Doc[]>("/api/documents").then(setDocs); }, []);
  return (
    <div>
      <h1 className="text-2xl font-bold text-navy-900 mb-1">Document Editor</h1>
      <p className="text-sm text-slate-500 mb-6">Choose a document to edit. Manual editing is optional — Quick Generator does everything automatically.</p>
      {!docs ? <Spinner /> : !docs.length ? (
        <EmptyState icon={<FileText className="h-6 w-6" />} title="No documents yet" text="Import an examination first." action={<Button variant="primary" onClick={() => navigate("import")}>Import a document</Button>} />
      ) : (
        <div className="grid grid-cols-3 gap-4">
          {docs.map((d) => (
            <button key={d.id} onClick={() => navigate(`editor/${d.id}`)} className="text-left rounded-xl bg-white border border-slate-200 p-4 hover:border-royal-400 hover:shadow-card transition">
              <div className="font-semibold text-navy-900 truncate">{d.title}</div>
              <div className="text-xs text-slate-500 mt-1">{d.source_name} · {d.question_count ?? 0} questions</div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function DocumentEditor({ id, route }: { id: string; route: Route }) {
  const toast = useToast();
  const [doc, setDoc] = useState<Doc | null>(null);
  const [model, setModel] = useState<DocModel | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [tid, setTid] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [sel, setSel] = useState<string | null>(route.params.get("block"));
  const [leftTab, setLeftTab] = useState<"structure" | "pages">("structure");
  const [rightTab, setRightTab] = useState<"content" | "style">("content");
  const [zoom, setZoom] = useState(1.0);
  const [save, setSave] = useState<{ state: "saved" | "dirty" | "saving" | "error"; at?: number }>({ state: "saved" });
  const [genJob, setGenJob] = useState<Job | null>(null);
  const [exportOpen, setExportOpen] = useState(false);
  const [families, setFamilies] = useState<string[]>([]);
  const undo = useRef<string[]>([]);
  const redo = useRef<string[]>([]);
  const lastKey = useRef<{ key: string; t: number } | null>(null);
  const clip = useRef<Block | null>(null);
  const center = useRef<HTMLDivElement>(null);
  const modelRef = useRef<DocModel | null>(null);
  modelRef.current = model;
  const [, force] = useState(0);
  const autosaveSec = useRef(20);
  const lastChange = useRef(0);

  // ---------------- load
  useEffect(() => {
    (async () => {
      try {
        const [d, t, f, st] = await Promise.all([api<Doc>(`/api/documents/${id}`), api<Template[]>("/api/templates"), api("/api/fonts"), api("/api/settings")]);
        setDoc(d); setTemplates(t);
        setFamilies(f.families.map((x: { family: string }) => x.family));
        autosaveSec.current = Number(st.autosave_seconds) || 20;
        const pre = route.params.get("template");
        setTid((pre && t.some((x) => x.id === pre) && pre) || d.template_id || (t.find((x) => x.is_default) || t[0]).id);
        try {
          setModel(await api<DocModel>(`/api/documents/${id}/model`));
        } catch {
          const j = await api<Job>(`/api/documents/${id}/extract`, { method: "POST" });
          const done = await pollJob(j.id, () => {});
          if (done.status !== "succeeded") throw new Error(done.error || "Extraction failed");
          setModel(await api<DocModel>(`/api/documents/${id}/model`));
        }
      } catch (e) { toast("error", errMsg(e)); }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // ---------------- history
  const commit = useCallback((next: DocModel, key?: string) => {
    const cur = modelRef.current;
    if (!cur) return;
    const now = Date.now();
    const coalesce = key && lastKey.current && lastKey.current.key === key && now - lastKey.current.t < 1200;
    if (!coalesce) { undo.current.push(JSON.stringify(cur)); if (undo.current.length > 200) undo.current.shift(); }
    lastKey.current = key ? { key, t: now } : null;
    redo.current = [];
    setModel(next);
    lastChange.current = now;
    setSave({ state: "dirty" });
  }, []);
  const doUndo = useCallback(() => {
    const prev = undo.current.pop();
    if (!prev || !modelRef.current) return;
    redo.current.push(JSON.stringify(modelRef.current));
    setModel(JSON.parse(prev)); lastKey.current = null; lastChange.current = Date.now(); setSave({ state: "dirty" }); force((x) => x + 1);
  }, []);
  const doRedo = useCallback(() => {
    const nxt = redo.current.pop();
    if (!nxt || !modelRef.current) return;
    undo.current.push(JSON.stringify(modelRef.current));
    setModel(JSON.parse(nxt)); lastKey.current = null; lastChange.current = Date.now(); setSave({ state: "dirty" }); force((x) => x + 1);
  }, []);

  const updateBlock = useCallback((bid: string, patch: Partial<Block>, key?: string) => {
    const m = modelRef.current;
    if (!m) return;
    commit({ ...m, blocks: m.blocks.map((b) => (b.id === bid ? { ...b, ...patch } : b)) }, key ? `${bid}:${key}` : undefined);
  }, [commit]);
  const updateStyle = (bid: string, patch: Record<string, unknown>) => {
    const b = model?.blocks.find((x) => x.id === bid);
    if (!b) return;
    const style = { ...(b.style || {}), ...patch };
    for (const k of Object.keys(style)) if (style[k] === null || style[k] === undefined || style[k] === "") delete style[k];
    updateBlock(bid, { style }, "style:" + Object.keys(patch).join(","));
  };
  const insertBlock = (b: Block, afterId?: string | null) => {
    const m = modelRef.current!;
    const idx = afterId ? m.blocks.findIndex((x) => x.id === afterId) : -1;
    const blocks = [...m.blocks];
    blocks.splice(idx >= 0 ? idx + 1 : blocks.length, 0, b);
    commit({ ...m, blocks });
    setSel(b.id);
  };
  const removeBlock = (bid: string) => {
    const m = modelRef.current!;
    if (bid.startsWith("ov:")) { commit({ ...m, overlays: m.overlays.filter((o) => "ov:" + o.id !== bid) }); setSel(null); return; }
    const i = m.blocks.findIndex((b) => b.id === bid);
    commit({ ...m, blocks: m.blocks.filter((b) => b.id !== bid) });
    setSel(m.blocks[i + 1]?.id || m.blocks[i - 1]?.id || null);
  };
  const moveBlock = (bid: string, beforeId: string | null) => {
    const m = modelRef.current!;
    if (bid === beforeId) return;
    const b = m.blocks.find((x) => x.id === bid);
    if (!b) return;
    const rest = m.blocks.filter((x) => x.id !== bid);
    const idx = beforeId ? rest.findIndex((x) => x.id === beforeId) : rest.length;
    rest.splice(idx < 0 ? rest.length : idx, 0, b);
    commit({ ...m, blocks: rest });
  };
  const shift = (bid: string, d: number) => {
    const m = modelRef.current!;
    const i = m.blocks.findIndex((x) => x.id === bid);
    const j = i + d;
    if (i < 0 || j < 0 || j >= m.blocks.length) return;
    const blocks = [...m.blocks];
    [blocks[i], blocks[j]] = [blocks[j], blocks[i]];
    commit({ ...m, blocks });
  };
  const duplicate = (bid: string) => {
    const b = modelRef.current!.blocks.find((x) => x.id === bid);
    if (b) insertBlock({ ...JSON.parse(JSON.stringify(b)), id: uid(), number_mode: b.type === "question" ? "auto" : b.number_mode }, bid);
  };

  // ---------------- save / autosave
  const saveNow = useCallback(async (auto = false) => {
    const m = modelRef.current;
    if (!m) return;
    setSave({ state: "saving" });
    try {
      await api(`/api/documents/${id}/model`, { method: "PUT", body: { model: m, autosave: auto } });
      setSave({ state: "saved", at: Date.now() });
    } catch (e) {
      setSave({ state: "error" });
      if (!auto) toast("error", errMsg(e));
    }
  }, [id, toast]);
  useEffect(() => {
    const t = setInterval(() => {
      if (save.state === "dirty" && Date.now() - lastChange.current > autosaveSec.current * 1000) saveNow(true);
    }, 2000);
    return () => clearInterval(t);
  }, [save.state, saveNow]);
  useEffect(() => {
    const h = (e: BeforeUnloadEvent) => { if (save.state === "dirty") { saveNow(true); e.preventDefault(); } };
    window.addEventListener("beforeunload", h);
    return () => { window.removeEventListener("beforeunload", h); if (save.state === "dirty") saveNow(true); };
  }, [save.state, saveNow]);

  // ---------------- preview (debounced; same engine as export)
  const reqN = useRef(0);
  useEffect(() => {
    if (!model || !tid) return;
    const n = ++reqN.current;
    const t = setTimeout(async () => {
      setLoadingPreview(true);
      try {
        const p = await api<Preview>(`/api/documents/${id}/preview`, { body: { template_id: tid, model } });
        if (n === reqN.current) { setPreview({ ...p, url: fileUrl(p.url) }); setPreviewError(null); }
      } catch (e) { if (n === reqN.current) setPreviewError(errMsg(e)); }
      finally { if (n === reqN.current) setLoadingPreview(false); }
    }, 550);
    return () => clearTimeout(t);
  }, [model, tid, id]);

  // ---------------- keyboard shortcuts
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const typing = ["INPUT", "TEXTAREA", "SELECT"].includes((e.target as HTMLElement)?.tagName);
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); saveNow(false); return; }
      if (typing) return;
      if (mod && e.key.toLowerCase() === "z" && !e.shiftKey) { e.preventDefault(); doUndo(); }
      else if (mod && (e.key.toLowerCase() === "y" || (e.key.toLowerCase() === "z" && e.shiftKey))) { e.preventDefault(); doRedo(); }
      else if (sel && mod && e.key.toLowerCase() === "c") { const b = modelRef.current?.blocks.find((x) => x.id === sel); if (b) { clip.current = JSON.parse(JSON.stringify(b)); toast("info", "Block copied"); } }
      else if (mod && e.key.toLowerCase() === "v" && clip.current) { e.preventDefault(); insertBlock({ ...JSON.parse(JSON.stringify(clip.current)), id: uid(), number_mode: clip.current.type === "question" ? "auto" : clip.current.number_mode }, sel); }
      else if (sel && mod && e.key.toLowerCase() === "d") { e.preventDefault(); duplicate(sel); }
      else if (sel && (e.key === "Delete" || e.key === "Backspace")) { e.preventDefault(); removeBlock(sel); }
      else if (sel && e.altKey && e.key === "ArrowUp") { e.preventDefault(); shift(sel, -1); }
      else if (sel && e.altKey && e.key === "ArrowDown") { e.preventDefault(); shift(sel, 1); }
      else if (e.key === "Escape") setSel(null);
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sel, doUndo, doRedo, saveNow]);

  // ---------------- generate
  const generate = useCallback(async (forceRun = false) => {
    if (save.state === "dirty") await saveNow(false);
    try {
      const j = await api<Job>("/api/generate", { body: { document_id: id, template_id: tid, options: forceRun ? { force: true } : {} } });
      setGenJob(j);
      await pollJob(j.id, setGenJob);
    } catch (e) { toast("error", errMsg(e)); }
  }, [id, tid, save.state, saveNow, toast]);
  const autoGen = useRef(false);
  useEffect(() => { if (model && tid && route.params.get("generate") && !autoGen.current) { autoGen.current = true; generate(false); } }, [model, tid, route.params, generate]);

  // scroll to selection / requested page
  const scrollToBlock = (bid: string) => {
    const pos = preview?.positions[bid]?.[0];
    if (!pos) return;
    center.current?.querySelector(`[data-pg="${pos.page}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  const initialScroll = useRef(false);
  useEffect(() => {
    if (!preview || initialScroll.current) return;
    initialScroll.current = true;
    const pg = route.params.get("page");
    setTimeout(() => {
      if (sel) scrollToBlock(sel);
      else if (pg) center.current?.querySelector(`[data-pg="${pg}"]`)?.scrollIntoView({ block: "start" });
    }, 400);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preview]);

  const fitted = useRef(false);
  useEffect(() => {
    // open at "fit width" so the whole page is visible in the centre panel
    if (fitted.current || !preview || !center.current) return;
    fitted.current = true;
    setZoom(Math.max(0.5, Math.min(1.4, (center.current.clientWidth - 110) / (595 * 1.25))));
  }, [preview]);
  const { doc: pdf } = usePdf(preview?.url);
  const numbers = preview?.numbers || {};
  const issuesByBlock = useMemo(() => {
    const m: Record<string, Issue[]> = {};
    for (const i of preview?.issues || []) if (i.block) (m[i.block] ||= []).push(i);
    return m;
  }, [preview]);
  const issuesByPage = useMemo(() => {
    const m: Record<number, Issue[]> = {};
    for (const i of preview?.issues || []) if (i.page) (m[i.page] ||= []).push(i);
    return m;
  }, [preview]);

  if (!doc || !model) return <div className="flex h-full items-center justify-center"><Spinner className="h-8 w-8" /></div>;
  const selBlock = model.blocks.find((b) => b.id === sel) || null;
  const selOverlay = sel?.startsWith("ov:") ? model.overlays.find((o) => "ov:" + o.id === sel) : null;
  const isOriginal = doc.import_mode === "original" && !!model.original_pages;
  const pageW = 595 * zoom * 1.25;

  return (
    <div className="h-full flex flex-col bg-slate-100">
      {/* toolbar */}
      <div className="flex items-center gap-2 px-4 h-14 bg-white border-b border-slate-200 shrink-0">
        <input className="font-semibold text-navy-900 text-[15px] bg-transparent outline-none focus:bg-slate-50 rounded px-2 py-1 w-72 truncate" value={model.title}
          onChange={(e) => commit({ ...model, title: e.target.value }, "title")} aria-label="Document title" />
        <div className="h-6 w-px bg-slate-200 mx-1" />
        <button className="p-2 rounded hover:bg-slate-100 disabled:opacity-30" title="Undo (Ctrl+Z)" disabled={!undo.current.length} onClick={doUndo}><Undo2 className="h-4 w-4" /></button>
        <button className="p-2 rounded hover:bg-slate-100 disabled:opacity-30" title="Redo (Ctrl+Y)" disabled={!redo.current.length} onClick={doRedo}><Redo2 className="h-4 w-4" /></button>
        <div className="text-xs w-36 text-slate-500 flex items-center gap-1.5">
          {save.state === "saving" && <><Loader2 className="h-3.5 w-3.5 animate-spin" />Saving…</>}
          {save.state === "saved" && <><span className="h-2 w-2 rounded-full bg-emerald-500" />{save.at ? `Saved ${new Date(save.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : "All changes saved"}</>}
          {save.state === "dirty" && <><span className="h-2 w-2 rounded-full bg-amber-500" />Unsaved — autosave on</>}
          {save.state === "error" && <><span className="h-2 w-2 rounded-full bg-brandred-600" />Save failed</>}
        </div>
        <Button size="sm" variant="ghost" icon={<Save className="h-4 w-4" />} onClick={() => saveNow(false)} title="Save version (Ctrl+S)">Save</Button>
        <div className="flex-1" />
        <span className="text-xs text-slate-500">Template</span>
        <Select className="w-72 h-8" value={tid} onChange={setTid} options={templates.map((t) => ({ value: t.id, label: t.name }))} />
        {preview && (
          <Badge tone={preview.summary.critical ? "red" : preview.summary.warning ? "amber" : "green"}>
            {preview.summary.critical ? `${preview.summary.critical} critical` : preview.summary.warning ? `${preview.summary.warning} warnings` : "Checks passed"}
          </Badge>
        )}
        <Button variant="secondary" onClick={async () => { if (save.state === "dirty") await saveNow(false); setExportOpen(true); }}>Export…</Button>
        <Button variant="primary" icon={<Zap className="h-4 w-4" />} onClick={() => generate(false)}>Generate PDF</Button>
      </div>

      <div className="flex-1 flex min-h-0">
        {/* left */}
        <div className="w-[290px] shrink-0 bg-white border-r border-slate-200 flex flex-col min-h-0">
          <div className="flex border-b border-slate-200 text-sm">
            {(["structure", "pages"] as const).map((t) => (
              <button key={t} onClick={() => setLeftTab(t)} className={cx("flex-1 py-2.5 font-medium capitalize", leftTab === t ? "text-royal-700 border-b-2 border-royal-600" : "text-slate-500 hover:text-navy-900")}>
                {t === "structure" ? (isOriginal ? "Original pages" : "Structure") : "Page thumbnails"}
              </button>
            ))}
          </div>
          <div className="flex-1 overflow-auto">
            {leftTab === "structure" && !isOriginal && (
              <StructureList blocks={model.blocks} sel={sel} numbers={numbers} issues={issuesByBlock}
                onSelect={(b) => { setSel(b); scrollToBlock(b); }} onMove={moveBlock} onAdd={(k) => insertBlock(newBlock(k), sel)} />
            )}
            {leftTab === "structure" && isOriginal && (
              <OriginalPagesPanel doc={doc} model={model} commit={commit} />
            )}
            {leftTab === "pages" && pdf && (
              <div className="p-3 grid grid-cols-2 gap-2">
                {Array.from({ length: pdf.numPages }, (_, i) => (
                  <button key={`${preview?.url}-${i}`} onClick={() => center.current?.querySelector(`[data-pg="${i + 1}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" })}
                    className="rounded border border-slate-200 p-1 hover:border-royal-400 relative">
                    <PdfPage doc={pdf} pageNumber={i + 1} width={112} />
                    <div className="text-[10px] text-slate-500 text-center">{i + 1}</div>
                    {issuesByPage[i + 1] && <span className="absolute top-1 right-1 h-2.5 w-2.5 rounded-full bg-amber-500" />}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* center */}
        <div className="flex-1 min-w-0 flex flex-col">
          <div className="flex items-center gap-2 px-4 py-2 text-xs text-slate-500 bg-slate-100 border-b border-slate-200">
            <button className="px-2 py-1 rounded hover:bg-white" onClick={() => setZoom((z) => Math.max(0.5, z - 0.1))}>−</button>
            <span className="tabular-nums w-10 text-center">{Math.round(zoom * 100)}%</span>
            <button className="px-2 py-1 rounded hover:bg-white" onClick={() => setZoom((z) => Math.min(2, z + 0.1))}>+</button>
            <button className="px-2 py-1 rounded hover:bg-white" onClick={() => { const w = center.current?.clientWidth || 900; setZoom(Math.max(0.5, (w - 80) / (595 * 1.25))); }}>Fit width</button>
            <button className="px-2 py-1 rounded hover:bg-white" onClick={() => { const h = center.current?.clientHeight || 800; setZoom(Math.max(0.4, (h - 40) / (842 * 1.25))); }}>Fit page</button>
            <div className="flex-1" />
            {loadingPreview && <span className="flex items-center gap-1.5"><Loader2 className="h-3.5 w-3.5 animate-spin" />Updating preview…</span>}
            {pdf && <span>{pdf.numPages} pages</span>}
            {!isOriginal && <span className="text-slate-400">Click an element to edit · drag to reorder</span>}
          </div>
          <div ref={center} className="flex-1 overflow-auto p-8" onMouseDown={(e) => { if (e.target === e.currentTarget) setSel(null); }}>
            {previewError && <div className="mb-4 rounded-lg bg-brandred-50 text-brandred-700 text-sm px-4 py-3">{previewError}</div>}
            {!pdf && <div className="flex justify-center py-24"><Spinner /></div>}
            {pdf && preview && (
              <div className="flex flex-col items-center gap-8">
                {Array.from({ length: pdf.numPages }, (_, i) => i + 1).map((pg) => (
                  <div key={pg} data-pg={pg} className="relative">
                    <div className="absolute -left-10 top-0 text-[11px] text-slate-400 tabular-nums">{pg}</div>
                    {issuesByPage[pg] && (
                      <div className="absolute -right-8 top-0 flex flex-col gap-1">
                        {issuesByPage[pg].slice(0, 3).map((iss, k) => <span key={k} title={iss.message}><IssueIcon level={iss.level} /></span>)}
                      </div>
                    )}
                    <PdfPage doc={pdf} pageNumber={pg} width={pageW}>
                      <PageOverlay page={pg} preview={preview} scale={pageW / preview.page_size[0]} sel={sel} setSel={setSel} issues={issuesByBlock}
                        onMove={moveBlock} model={model} commit={commit} draggableFlow={!isOriginal} />
                    </PdfPage>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* right */}
        <div className="w-[340px] shrink-0 bg-white border-l border-slate-200 flex flex-col min-h-0">
          {selBlock ? (
            <>
              <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-100">
                {React.createElement(ICONS[selBlock.type] || FileText, { className: "h-4 w-4 text-royal-600" })}
                <div className="font-semibold text-navy-900 capitalize text-sm flex-1">{selBlock.type === "question" ? `Question ${numbers[selBlock.id] ?? selBlock.number ?? ""}` : selBlock.type.replace("_", " ")}</div>
                <button title="Move up (Alt+↑)" className="p-1.5 rounded hover:bg-slate-100" onClick={() => shift(selBlock.id, -1)}><ArrowUp className="h-4 w-4" /></button>
                <button title="Move down (Alt+↓)" className="p-1.5 rounded hover:bg-slate-100" onClick={() => shift(selBlock.id, 1)}><ArrowDown className="h-4 w-4" /></button>
                <button title="Duplicate (Ctrl+D)" className="p-1.5 rounded hover:bg-slate-100" onClick={() => duplicate(selBlock.id)}><Copy className="h-4 w-4" /></button>
                <button title="Delete (Del)" className="p-1.5 rounded hover:bg-brandred-50 text-brandred-600" onClick={() => removeBlock(selBlock.id)}><Trash2 className="h-4 w-4" /></button>
              </div>
              <div className="flex border-b border-slate-100 text-sm">
                {(["content", "style"] as const).map((t) => (
                  <button key={t} onClick={() => setRightTab(t)} className={cx("flex-1 py-2 font-medium capitalize", rightTab === t ? "text-royal-700 border-b-2 border-royal-600" : "text-slate-500")}>{t}</button>
                ))}
              </div>
              <div className="flex-1 overflow-auto p-4 space-y-4">
                {issuesByBlock[selBlock.id] && <IssueList issues={issuesByBlock[selBlock.id]} />}
                {selBlock.source?.ocr && <div className="text-xs rounded-md bg-amber-50 text-amber-800 px-2.5 py-1.5">Recognised by OCR{selBlock.source.confidence ? ` (${Math.round(selBlock.source.confidence * 100)}% confidence)` : ""} — please proofread.</div>}
                {rightTab === "content" ? <ContentProps b={selBlock} update={updateBlock}
                  insertImage={(after, a) => insertBlock({ id: uid(), type: "image", asset: a.id, width: a.width, height: a.height, kind: "image", layout: "center", caption: null }, after)} /> : <StyleProps b={selBlock} families={families} setStyle={(p) => updateStyle(selBlock.id, p)} />}
              </div>
            </>
          ) : selOverlay ? (
            <OverlayProps ov={selOverlay} model={model} commit={commit} onDelete={() => removeBlock(sel!)} />
          ) : (
            <DocumentPanel model={model} preview={preview} commit={commit} onOpen={(i) => { if (i.block) { setSel(i.block); scrollToBlock(i.block); } else if (i.page) center.current?.querySelector(`[data-pg="${i.page}"]`)?.scrollIntoView({ behavior: "smooth" }); }} />
          )}
        </div>
      </div>

      <ExportDialog open={exportOpen} onClose={() => setExportOpen(false)} documentId={id} templateId={tid} title={model.title} blocks={model.blocks} />
      <Modal open={!!genJob} onClose={() => { if (genJob && !["queued", "running"].includes(genJob.status)) setGenJob(null); }} title="Generate PDF" width="max-w-4xl">
        {genJob && (["queued", "running"].includes(genJob.status) || genJob.status === "failed") && <><JobTimeline job={genJob} /><LogTail job={genJob} /></>}
        {genJob && genJob.result && genJob.status !== "failed" && <ResultPanel job={genJob} templates={templates} onRegenerate={() => generate(true)} />}
      </Modal>
    </div>
  );
}

// ====================================================================== left: structure
function StructureList({ blocks, sel, numbers, issues, onSelect, onMove, onAdd }: {
  blocks: Block[]; sel: string | null; numbers: Record<string, string>; issues: Record<string, Issue[]>;
  onSelect: (id: string) => void; onMove: (id: string, before: string | null) => void; onAdd: (k: string) => void;
}) {
  const [menu, setMenu] = useState(false);
  const [over, setOver] = useState<string | null>(null);
  const selRef = useRef<HTMLDivElement>(null);
  useEffect(() => { selRef.current?.scrollIntoView({ block: "nearest" }); }, [sel]);
  return (
    <div className="p-2">
      <div className="relative mb-2">
        <Button size="sm" variant="primary" className="w-full" icon={<Plus className="h-4 w-4" />} onClick={() => setMenu(!menu)}>Add element <ChevronDown className="h-3.5 w-3.5" /></Button>
        {menu && (
          <div className="absolute z-20 left-0 right-0 mt-1 rounded-xl bg-white shadow-lift border border-slate-100 py-1 text-sm" onMouseLeave={() => setMenu(false)}>
            {[["mcq", "Multiple-choice question"], ["true_false", "True / False question"], ["gap_fill", "Gap-filling question"], ["writing", "Writing task"],
              ["section", "Section (page layout)"], ["heading", "Heading"], ["instruction", "Instruction"], ["paragraph", "Text / reading passage"], ["table", "Table"],
              ["answer_space", "Answer lines"], ["page_break", "Page break"]].map(([k, l]) => (
              <button key={k} className="w-full text-left px-3 py-1.5 hover:bg-slate-50" onClick={() => { setMenu(false); onAdd(k); }}>{l}</button>
            ))}
            <div className="px-3 py-1 text-[11px] text-slate-400">Images: select an element, then use “Images” in its properties, or add a picture block from Content.</div>
          </div>
        )}
      </div>
      {blocks.map((b) => {
        const Icon = ICONS[b.type] || FileText;
        const iss = issues[b.id];
        return (
          <div key={b.id} ref={sel === b.id ? selRef : undefined} draggable
            onDragStart={(e) => { e.dataTransfer.setData("text/ptd-block", b.id); e.dataTransfer.effectAllowed = "move"; }}
            onDragOver={(e) => { e.preventDefault(); setOver(b.id); }} onDragLeave={() => setOver(null)}
            onDrop={(e) => { e.preventDefault(); setOver(null); const src = e.dataTransfer.getData("text/ptd-block"); if (src) onMove(src, b.id); }}
            onClick={() => onSelect(b.id)}
            className={cx("group flex items-center gap-1.5 rounded-md px-1.5 py-1.5 text-[12.5px] cursor-pointer border-t-2",
              over === b.id ? "border-royal-500" : "border-transparent", sel === b.id ? "bg-royal-50 text-royal-800" : "hover:bg-slate-50 text-slate-700",
              b.type === "section" && "font-semibold mt-2")}>
            <GripVertical className="h-3.5 w-3.5 text-slate-300 group-hover:text-slate-500 shrink-0 cursor-grab" />
            <Icon className={cx("h-3.5 w-3.5 shrink-0", b.type === "question" ? "text-royal-600" : "text-slate-400")} />
            <span className="truncate flex-1">{blockLabel(b, numbers)}</span>
            {iss && <IssueIcon level={iss[0].level} className="h-3.5 w-3.5" />}
          </div>
        );
      })}
      <div className="h-8" onDragOver={(e) => e.preventDefault()} onDrop={(e) => { const src = e.dataTransfer.getData("text/ptd-block"); if (src) onMove(src, null); }} />
    </div>
  );
}

function OriginalPagesPanel({ doc, model, commit }: { doc: Doc; model: DocModel; commit: (m: DocModel) => void }) {
  const pages = model.original_pages || [];
  const set = (p: typeof pages) => commit({ ...model, original_pages: p });
  return (
    <div className="p-3 space-y-2">
      <div className="text-xs text-slate-500">Original pages are embedded unchanged. Reorder, rotate or exclude them; add text or images as overlays from the Document panel.</div>
      {pages.map((p, i) => (
        <div key={`${p.index}-${i}`} className={cx("flex items-center gap-2 rounded-lg border p-1.5", p.include ? "border-slate-200" : "border-dashed opacity-50")}>
          <img src={fileUrl(`/api/documents/${doc.id}/original/pages/${p.index + 1}.png?dpi=30`)} alt="" className="h-16 w-12 object-contain bg-slate-50 rounded" style={{ transform: `rotate(${p.rotation}deg)` }} />
          <div className="flex-1 text-xs text-slate-600">Original page {p.index + 1}{p.rotation ? ` · ${p.rotation}°` : ""}</div>
          <button className="p-1 hover:bg-slate-100 rounded" title="Up" onClick={() => { if (i) { const n = [...pages]; [n[i - 1], n[i]] = [n[i], n[i - 1]]; set(n); } }}><ArrowUp className="h-3.5 w-3.5" /></button>
          <button className="p-1 hover:bg-slate-100 rounded" title="Down" onClick={() => { if (i < pages.length - 1) { const n = [...pages]; [n[i + 1], n[i]] = [n[i], n[i + 1]]; set(n); } }}><ArrowDown className="h-3.5 w-3.5" /></button>
          <button className="p-1 hover:bg-slate-100 rounded" title="Rotate" onClick={() => set(pages.map((x, k) => (k === i ? { ...x, rotation: (x.rotation + 90) % 360 } : x)))}><RotateCw className="h-3.5 w-3.5" /></button>
          <input type="checkbox" checked={p.include} title="Include" onChange={() => set(pages.map((x, k) => (k === i ? { ...x, include: !x.include } : x)))} />
        </div>
      ))}
    </div>
  );
}

// ====================================================================== center: overlay boxes
function PageOverlay({ page, preview, scale, sel, setSel, issues, onMove, model, commit, draggableFlow }: {
  page: number; preview: Preview; scale: number; sel: string | null; setSel: (id: string) => void; issues: Record<string, Issue[]>;
  onMove: (id: string, before: string | null) => void; model: DocModel; commit: (m: DocModel, key?: string) => void; draggableFlow: boolean;
}) {
  const [drag, setDrag] = useState<{ id: string; dx: number; dy: number } | null>(null);
  const boxes = Object.entries(preview.positions).flatMap(([bid, rects]) => rects.filter((r) => r.page === page).map((r, k) => ({ bid, r, k })));
  const startOverlayDrag = (e: React.MouseEvent, bid: string) => {
    e.preventDefault(); e.stopPropagation();
    setSel(bid);
    const ov = model.overlays.find((o) => "ov:" + o.id === bid);
    if (!ov) return;
    const sx = e.clientX, sy = e.clientY;
    const move = (ev: MouseEvent) => setDrag({ id: bid, dx: ev.clientX - sx, dy: ev.clientY - sy });
    const up = (ev: MouseEvent) => {
      window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up);
      setDrag(null);
      const dxmm = (ev.clientX - sx) / scale / MM, dymm = (ev.clientY - sy) / scale / MM;
      if (Math.abs(dxmm) + Math.abs(dymm) < 0.3) return;
      commit({ ...model, overlays: model.overlays.map((o) => ("ov:" + o.id === bid ? { ...o, x_mm: Math.round((o.x_mm + dxmm) * 10) / 10, y_mm: Math.round((o.y_mm + dymm) * 10) / 10 } : o)) });
    };
    window.addEventListener("mousemove", move); window.addEventListener("mouseup", up);
  };
  return (
    <div className="absolute inset-0">
      {boxes.map(({ bid, r, k }) => {
        if (bid.startsWith("page:") || bid === "__answer_sheet__") return null;
        const isOv = bid.startsWith("ov:");
        const off = drag?.id === bid ? { dx: drag.dx, dy: drag.dy } : { dx: 0, dy: 0 };
        const crit = issues[bid]?.some((i) => i.level === "critical");
        return (
          <div key={`${bid}-${k}`}
            className={cx("absolute rounded-[2px] cursor-pointer", sel === bid ? "sel-box" : "hover-box", crit && sel !== bid && "outline outline-2 outline-brandred-500", isOv && "cursor-move")}
            style={{ left: r.x0 * scale - 3 + off.dx, top: r.y0 * scale - 2 + off.dy, width: (r.x1 - r.x0) * scale + 6, height: (r.y1 - r.y0) * scale + 4 }}
            draggable={!isOv && draggableFlow}
            onDragStart={(e) => { e.dataTransfer.setData("text/ptd-block", bid); }}
            onDragOver={(e) => { if (!isOv) e.preventDefault(); }}
            onDrop={(e) => { e.preventDefault(); const src = e.dataTransfer.getData("text/ptd-block"); if (src && src !== bid) onMove(src, bid); }}
            onMouseDown={(e) => { if (isOv) startOverlayDrag(e, bid); }}
            onClick={(e) => { e.stopPropagation(); setSel(bid); }}
            title={isOv ? "Drag to move" : "Click to edit · drag onto another element to move it before that element"} />
        );
      })}
    </div>
  );
}

// ====================================================================== right: properties
function ContentProps({ b, update, insertImage }: { b: Block; update: (id: string, p: Partial<Block>, key?: string) => void; insertImage: (after: string, a: Asset) => void }) {
  const [picker, setPicker] = useState<null | "block" | "question">(null);
  const u = (p: Partial<Block>, key?: string) => update(b.id, p, key);
  return (
    <div className="space-y-4">
      {b.type === "question" && (
        <>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Numbering" hint="Automatic numbers update when questions are moved, inserted or deleted. The question text is never changed.">
              <Select value={b.number_mode || "auto"} onChange={(v) => u({ number_mode: v as "auto" | "manual" })} options={[{ value: "auto", label: "Automatic" }, { value: "manual", label: "Manual" }]} />
            </Field>
            <Field label="Number"><TextInput value={b.number || ""} disabled={b.number_mode !== "manual"} onChange={(e) => u({ number: e.target.value }, "number")} /></Field>
          </div>
          <Field label="Question type"><Select value={b.qtype || "open"} onChange={(v) => u({ qtype: v })} options={QTYPES.map(([v, l]) => ({ value: v, label: l }))} /></Field>
          <Field label="Question text"><TextArea rows={4} value={b.text || ""} onChange={(e) => u({ text: e.target.value }, "text")} /></Field>
          <div>
            <div className="flex items-center justify-between mb-1"><span className="text-[12px] font-semibold text-slate-600">Answer options</span>
              <button className="text-xs text-royal-700 hover:underline" onClick={() => {
                const opts = b.options || [];
                const last = opts[opts.length - 1]?.label || "@";
                const next = /^[A-Za-z]$/.test(last) ? String.fromCharCode(last.charCodeAt(0) + 1) : String(opts.length + 1);
                u({ options: [...opts, { label: next, text: "" }] });
              }}>+ Add option</button>
            </div>
            <div className="space-y-1.5">
              {(b.options || []).map((o, i) => (
                <div key={i} className="flex gap-1.5 items-center">
                  <TextInput className="w-11 text-center px-1" value={o.label} onChange={(e) => u({ options: b.options!.map((x, k) => (k === i ? { ...x, label: e.target.value } : x)) }, `optl${i}`)} />
                  <TextInput value={o.text} onChange={(e) => u({ options: b.options!.map((x, k) => (k === i ? { ...x, text: e.target.value } : x)) }, `opt${i}`)} />
                  <button className="p-1 text-slate-400 hover:text-brandred-600" title="Remove option" onClick={() => u({ options: b.options!.filter((_, k) => k !== i) })}><Trash2 className="h-3.5 w-3.5" /></button>
                </div>
              ))}
              {!b.options?.length && <div className="text-xs text-slate-400">No options (open question).</div>}
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <Field label="Points"><TextInput value={b.points ?? ""} onChange={(e) => u({ points: e.target.value || null }, "points")} /></Field>
            <Field label="Difficulty"><Select value={b.difficulty || ""} onChange={(v) => u({ difficulty: v || null })} options={[{ value: "", label: "—" }, { value: "easy", label: "Easy" }, { value: "medium", label: "Medium" }, { value: "hard", label: "Hard" }]} /></Field>
            <Field label="Correct"><Select value={b.correct || ""} onChange={(v) => u({ correct: v || null })} options={[{ value: "", label: "—" }, ...(b.options || []).map((o) => ({ value: o.label, label: o.label }))]} /></Field>
          </div>
          <Field label="Answer lines" hint="Ruled lines for written answers"><NumberInput value={b.answer_lines ?? 0} min={0} max={40} onChange={(v) => u({ answer_lines: v ?? 0 })} /></Field>
          <div>
            <div className="flex items-center justify-between mb-1"><span className="text-[12px] font-semibold text-slate-600">Images</span><button className="text-xs text-royal-700 hover:underline" onClick={() => setPicker("question")}>+ Add image</button></div>
            <div className="grid grid-cols-3 gap-2">
              {(b.images || []).map((im, i) => (
                <div key={i} className="relative rounded border border-slate-200 p-1">
                  <img src={fileUrl(`/api/assets/${im.asset}/thumb?size=160`)} alt="" className="h-16 w-full object-contain" />
                  <button className="absolute -top-1.5 -right-1.5 bg-white rounded-full shadow p-0.5 text-brandred-600" onClick={() => u({ images: b.images!.filter((_, k) => k !== i) })}><Trash2 className="h-3 w-3" /></button>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
      {b.type === "section" && (
        <>
          <Field label="Section title"><TextInput value={b.title || ""} onChange={(e) => u({ title: e.target.value }, "title")} /></Field>
          <Field label="Page layout" hint="Different layouts can be used in the same document. Changing layout starts a new page."><Select value={b.layout || "standard"} onChange={(v) => u({ layout: v })} options={LAYOUTS.map(([v, l]) => ({ value: v, label: l }))} /></Field>
          <Toggle label="Restart automatic numbering" checked={!!b.restart_numbering} onChange={(v) => u({ restart_numbering: v })} />
        </>
      )}
      {b.type === "heading" && (
        <>
          <Field label="Heading text"><TextInput value={b.text || ""} onChange={(e) => u({ text: e.target.value }, "text")} /></Field>
          <Field label="Level"><Select value={String(b.level || 2)} onChange={(v) => u({ level: Number(v) })} options={[{ value: "1", label: "Heading 1" }, { value: "2", label: "Heading 2" }, { value: "3", label: "Heading 3" }]} /></Field>
        </>
      )}
      {(b.type === "instruction" || b.type === "paragraph") && (
        <Field label={b.type === "instruction" ? "Instruction" : "Text"}><TextArea rows={b.type === "paragraph" ? 14 : 4} value={b.text || ""} onChange={(e) => u({ text: e.target.value }, "text")} /></Field>
      )}
      {b.type === "table" && <TableEditor b={b} u={u} />}
      {b.type === "image" && (
        <>
          <div className="rounded-lg border border-slate-200 p-2 bg-slate-50"><img src={fileUrl(`/api/assets/${b.asset}/thumb?size=500`)} alt="" className="max-h-48 mx-auto object-contain" /></div>
          <Button size="sm" className="w-full" onClick={() => setPicker("block")}>Replace image…</Button>
          <Field label="Caption"><TextInput value={b.caption || ""} onChange={(e) => u({ caption: e.target.value || null }, "caption")} /></Field>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Kind"><Select value={b.kind || "image"} onChange={(v) => u({ kind: v })} options={[{ value: "image", label: "Image" }, { value: "map", label: "Map" }, { value: "diagram", label: "Diagram" }]} /></Field>
            <Field label="Placement"><Select value={b.layout || "center"} onChange={(v) => u({ layout: v })} options={[{ value: "center", label: "Centered" }, { value: "full", label: "Full width" }, { value: "inline", label: "Inline (natural size)" }]} /></Field>
          </div>
        </>
      )}
      {b.type === "answer_space" && <Field label="Number of lines"><NumberInput value={b.lines ?? 3} min={1} max={40} onChange={(v) => u({ lines: v ?? 3 })} /></Field>}
      {b.type === "page_break" && <div className="text-sm text-slate-500">Forces the next element to start on a new page.</div>}
      {b.type !== "question" && b.type !== "page_break" && (
        <Button size="sm" variant="ghost" icon={<ImageIcon className="h-4 w-4" />} onClick={() => setPicker("block")} className={b.type === "image" ? "hidden" : ""}>Insert picture after this element</Button>
      )}
      <AssetPicker open={!!picker} onClose={() => setPicker(null)} onPick={(a) => {
        if (picker === "question") u({ images: [...(b.images || []), { asset: a.id, width: a.width, height: a.height, kind: "image" }] });
        else if (b.type === "image") u({ asset: a.id, width: a.width, height: a.height });
        else insertImage(b.id, a);
        setPicker(null);
      }} />
    </div>
  );
}

function TableEditor({ b, u }: { b: Block; u: (p: Partial<Block>, key?: string) => void }) {
  const rows = b.rows || [[""]];
  const cols = Math.max(...rows.map((r) => r.length));
  const set = (r: number, c: number, v: string) => u({ rows: rows.map((row, i) => (i === r ? Array.from({ length: cols }, (_, j) => (j === c ? v : row[j] || "")) : row)) }, `cell${r}-${c}`);
  return (
    <div className="space-y-3">
      <div className="flex gap-1.5 flex-wrap">
        <Button size="sm" onClick={() => u({ rows: [...rows, Array(cols).fill("")] })}>+ Row</Button>
        <Button size="sm" onClick={() => u({ rows: rows.map((r) => [...r, ""]) })}>+ Column</Button>
        <Button size="sm" disabled={rows.length <= 1} onClick={() => u({ rows: rows.slice(0, -1) })}>− Row</Button>
        <Button size="sm" disabled={cols <= 1} onClick={() => u({ rows: rows.map((r) => r.slice(0, cols - 1)) })}>− Column</Button>
      </div>
      <Field label="Header rows" hint="Header rows repeat at the top of each page when a table continues"><NumberInput value={b.header_rows ?? 1} min={0} max={5} onChange={(v) => u({ header_rows: v ?? 0 })} /></Field>
      <div className="overflow-auto max-h-[420px] border border-slate-200 rounded-lg">
        <table className="text-xs">
          <tbody>
            {rows.map((row, r) => (
              <tr key={r} className={r < (b.header_rows ?? 1) ? "bg-royal-50" : ""}>
                {Array.from({ length: cols }, (_, c) => (
                  <td key={c} className="border border-slate-100 p-0"><input className="w-28 px-1.5 py-1 bg-transparent outline-none focus:bg-white" value={row[c] || ""} onChange={(e) => set(r, c, e.target.value)} /></td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TriState({ value, onChange, icon, label }: { value: boolean | undefined; onChange: (v: boolean | null) => void; icon: React.ReactNode; label: string }) {
  return (
    <button title={`${label}: ${value === undefined ? "template default" : value ? "on" : "off"}`} onClick={() => onChange(value === undefined ? true : value ? false : null)}
      className={cx("h-8 w-8 rounded-md border flex items-center justify-center", value === undefined ? "border-slate-200 text-slate-400" : value ? "border-royal-500 bg-royal-50 text-royal-700" : "border-slate-300 bg-slate-100 text-slate-500 line-through")}>{icon}</button>
  );
}

function StyleProps({ b, families, setStyle }: { b: Block; families: string[]; setStyle: (p: Record<string, unknown>) => void }) {
  const s = b.style || {};
  const textual = !["image", "page_break", "answer_space"].includes(b.type);
  return (
    <div className="space-y-4">
      <div className="text-xs text-slate-500">Overrides apply only to this element. Empty values use the template.</div>
      {textual && (
        <>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Font family"><Select value={s.font_family || ""} onChange={(v) => setStyle({ font_family: v || null })} options={[{ value: "", label: "Template default" }, ...families.map((f) => ({ value: f, label: f }))]} /></Field>
            <Field label="Font size (pt)"><NumberInput value={s.font_size} min={6} max={48} step={0.5} placeholder="default" onChange={(v) => setStyle({ font_size: v })} /></Field>
          </div>
          <div className="flex items-center gap-1.5">
            <TriState label="Bold" value={s.bold} onChange={(v) => setStyle({ bold: v })} icon={<Bold className="h-4 w-4" />} />
            <TriState label="Italic" value={s.italic} onChange={(v) => setStyle({ italic: v })} icon={<Italic className="h-4 w-4" />} />
            <div className="w-px h-6 bg-slate-200 mx-1" />
            {([["left", AlignLeft], ["center", AlignCenter], ["right", AlignRight], ["justify", AlignJustify]] as const).map(([a, I]) => (
              <button key={a} title={`Align ${a}`} onClick={() => setStyle({ align: s.align === a ? null : a })}
                className={cx("h-8 w-8 rounded-md border flex items-center justify-center", s.align === a ? "border-royal-500 bg-royal-50 text-royal-700" : "border-slate-200 text-slate-500")}><I className="h-4 w-4" /></button>
            ))}
          </div>
          <Field label="Text colour"><ColorInput value={s.color} onChange={(v) => setStyle({ color: v })} /></Field>
          <Field label="Background colour"><ColorInput value={s.bg} onChange={(v) => setStyle({ bg: v })} /></Field>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Border colour"><ColorInput value={s.border} onChange={(v) => setStyle({ border: v })} /></Field>
            <Field label="Padding (mm)"><NumberInput value={s.padding} min={0} max={20} step={0.5} placeholder="0" onChange={(v) => setStyle({ padding: v })} /></Field>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <Field label="Space before"><NumberInput value={s.space_before} min={0} max={60} step={0.5} placeholder="mm" onChange={(v) => setStyle({ space_before: v })} /></Field>
            <Field label="Space after"><NumberInput value={s.space_after} min={0} max={60} step={0.5} placeholder="mm" onChange={(v) => setStyle({ space_after: v })} /></Field>
            <Field label="Indent"><NumberInput value={s.indent} min={0} max={60} step={0.5} placeholder="mm" onChange={(v) => setStyle({ indent: v })} /></Field>
          </div>
        </>
      )}
      {b.type === "question" && (
        <Field label="Option layout"><Select value={s.option_layout || ""} onChange={(v) => setStyle({ option_layout: v || null })}
          options={[{ value: "", label: "Template default" }, { value: "auto", label: "Automatic" }, { value: "vertical", label: "Vertical list" }, { value: "two_column", label: "Two columns" }, { value: "grid4", label: "Four columns" }]} /></Field>
      )}
      {b.type === "image" && (
        <>
          <Field label="Width (% of column)"><Slider value={s.width_pct ?? 90} min={10} max={100} step={1} format={(v) => `${v}%`} onChange={(v) => setStyle({ width_pct: v, width_mm: null })} /></Field>
          <Field label="Exact width (mm)"><NumberInput value={s.width_mm} min={10} max={400} placeholder="auto" onChange={(v) => setStyle({ width_mm: v })} /></Field>
          <Field label="Transparency"><Slider value={s.opacity ?? 1} min={0.1} max={1} step={0.05} format={(v) => `${Math.round(v * 100)}%`} onChange={(v) => setStyle({ opacity: v })} /></Field>
          <Field label="Alignment"><Select value={s.align || ""} onChange={(v) => setStyle({ align: v || null })} options={[{ value: "", label: "Template default" }, { value: "left", label: "Left" }, { value: "center", label: "Center" }, { value: "right", label: "Right" }]} /></Field>
        </>
      )}
      <div className="border-t border-slate-100 pt-3 space-y-1">
        <div className="text-[12px] font-semibold text-slate-600 mb-1">Page-break rules</div>
        <Select value={s.keep_together === undefined ? "" : s.keep_together ? "yes" : "no"} onChange={(v) => setStyle({ keep_together: v === "" ? null : v === "yes" })}
          options={[{ value: "", label: "Keep together: template default" }, { value: "yes", label: "Keep together on one page" }, { value: "no", label: "Allow splitting across pages" }]} />
        <Toggle label="Start on a new page" checked={!!s.page_break_before} onChange={(v) => setStyle({ page_break_before: v || null })} />
      </div>
      {Object.keys(s).length > 0 && <Button size="sm" variant="ghost" onClick={() => setStyle(Object.fromEntries(Object.keys(s).map((k) => [k, null])))}>Reset all overrides</Button>}
    </div>
  );
}

function DocumentPanel({ model, preview, commit, onOpen }: { model: DocModel; preview: Preview | null; commit: (m: DocModel, key?: string) => void; onOpen: (i: Issue) => void }) {
  const [picker, setPicker] = useState(false);
  const page = 1 + (preview?.cover_pages || 0);
  const add = (ov: Record<string, unknown>) => commit({ ...model, overlays: [...(model.overlays || []), { id: Math.random().toString(16).slice(2, 10), page, x_mm: 30, y_mm: 60, w_mm: 70, h_mm: 18, opacity: 1, ...ov }] });
  return (
    <div className="flex-1 overflow-auto p-4 space-y-5">
      <div>
        <div className="font-semibold text-navy-900 text-sm mb-2">Document check</div>
        {preview ? <IssueList issues={preview.issues} onOpen={onOpen} max={30} /> : <Spinner />}
      </div>
      <div className="border-t border-slate-100 pt-4">
        <div className="font-semibold text-navy-900 text-sm mb-1">Free-positioned elements</div>
        <div className="text-xs text-slate-500 mb-3">Add a text box or picture anywhere on a page and drag it into place.</div>
        <div className="flex gap-2">
          <Button size="sm" icon={<Type className="h-4 w-4" />} onClick={() => add({ type: "text", text: "Text box", font_size: 12, color: "#111827" })}>Text box</Button>
          <Button size="sm" icon={<ImageIcon className="h-4 w-4" />} onClick={() => setPicker(true)}>Picture</Button>
        </div>
        <div className="mt-3 space-y-1">
          {(model.overlays || []).map((o) => <div key={o.id} className="text-xs text-slate-600 flex items-center gap-2"><SquareDashed className="h-3.5 w-3.5" />Page {o.page}: {o.type === "image" ? "picture" : `“${String(o.text).slice(0, 28)}”`}</div>)}
        </div>
      </div>
      <div className="border-t border-slate-100 pt-4 text-xs text-slate-500 space-y-1">
        <div className="font-semibold text-slate-600 mb-1">Keyboard shortcuts</div>
        <div>Ctrl+Z / Ctrl+Y — undo / redo</div><div>Ctrl+S — save version</div><div>Ctrl+C / Ctrl+V — copy / paste element</div>
        <div>Ctrl+D — duplicate · Del — delete</div><div>Alt+↑ / Alt+↓ — move element</div><div>Esc — deselect</div>
      </div>
      <AssetPicker open={picker} onClose={() => setPicker(false)} onPick={(a) => { setPicker(false); add({ type: "image", asset: a.id, w_mm: 60, h_mm: 60 * (a.height / Math.max(a.width, 1)) }); }} />
    </div>
  );
}

function OverlayProps({ ov, model, commit, onDelete }: { ov: any; model: DocModel; commit: (m: DocModel, key?: string) => void; onDelete: () => void }) {
  const u = (p: Record<string, unknown>, key?: string) => commit({ ...model, overlays: model.overlays.map((o) => (o.id === ov.id ? { ...o, ...p } : o)) }, key ? `ov${ov.id}${key}` : undefined);
  return (
    <div className="flex-1 overflow-auto">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-100">
        <SquareDashed className="h-4 w-4 text-royal-600" /><div className="font-semibold text-navy-900 text-sm flex-1">{ov.type === "image" ? "Picture" : "Text box"}</div>
        <button className="p-1.5 rounded hover:bg-brandred-50 text-brandred-600" onClick={onDelete} title="Delete"><Trash2 className="h-4 w-4" /></button>
      </div>
      <div className="p-4 space-y-3">
        {ov.type !== "image" && (
          <>
            <Field label="Text"><TextArea rows={3} value={ov.text} onChange={(e) => u({ text: e.target.value }, "text")} /></Field>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Font size"><NumberInput value={ov.font_size} min={6} max={96} onChange={(v) => u({ font_size: v ?? 12 })} /></Field>
              <Field label="Align"><Select value={ov.align || "left"} onChange={(v) => u({ align: v })} options={[{ value: "left", label: "Left" }, { value: "center", label: "Center" }, { value: "right", label: "Right" }]} /></Field>
            </div>
            <Toggle label="Bold" checked={!!ov.bold} onChange={(v) => u({ bold: v })} />
            <Field label="Colour"><ColorInput value={ov.color} onChange={(v) => u({ color: v })} /></Field>
            <Field label="Background"><ColorInput value={ov.bg} onChange={(v) => u({ bg: v })} /></Field>
          </>
        )}
        <div className="grid grid-cols-2 gap-2">
          <Field label="Page"><NumberInput value={ov.page} min={1} onChange={(v) => u({ page: v ?? 1 })} /></Field>
          <Field label="Rotation (°)"><NumberInput value={ov.rotation ?? 0} min={-180} max={180} onChange={(v) => u({ rotation: v ?? 0 })} /></Field>
          <Field label="X (mm)"><NumberInput value={ov.x_mm} step={0.5} onChange={(v) => u({ x_mm: v ?? 0 }, "x")} /></Field>
          <Field label="Y (mm)"><NumberInput value={ov.y_mm} step={0.5} onChange={(v) => u({ y_mm: v ?? 0 }, "y")} /></Field>
          <Field label="Width (mm)"><NumberInput value={ov.w_mm} min={2} step={0.5} onChange={(v) => u({ w_mm: v ?? 10 }, "w")} /></Field>
          <Field label="Height (mm)"><NumberInput value={ov.h_mm} min={2} step={0.5} onChange={(v) => u({ h_mm: v ?? 10 }, "h")} /></Field>
        </div>
        <Field label="Transparency"><Slider value={ov.opacity ?? 1} min={0.05} max={1} step={0.05} format={(v) => `${Math.round(v * 100)}%`} onChange={(v) => u({ opacity: v }, "op")} /></Field>
      </div>
    </div>
  );
}

export function AssetPicker({ open, onClose, onPick, kinds = "image,logo,extracted,watermark,background" }: { open: boolean; onClose: () => void; onPick: (a: Asset) => void; kinds?: string }) {
  const [assets, setAssets] = useState<Asset[] | null>(null);
  const toast = useToast();
  const load = useCallback(() => api<Asset[]>(`/api/assets?kind=${kinds}`).then(setAssets), [kinds]);
  useEffect(() => { if (open) load(); }, [open, load]);
  const onUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = Array.from(e.target.files || []);
    e.target.value = "";
    try { for (const file of f) await upload("/api/assets", { kind: "image" }, [file]); await load(); } catch (x) { toast("error", errMsg(x)); }
  };
  return (
    <Modal open={open} onClose={onClose} title="Choose an image" width="max-w-3xl">
      <label className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm cursor-pointer hover:bg-slate-50 mb-4">
        <Plus className="h-4 w-4" />Upload image<input type="file" accept=".png,.jpg,.jpeg,.svg,.gif,.bmp,.tif,.tiff,.webp" multiple className="hidden" onChange={onUpload} />
      </label>
      {!assets ? <Spinner /> : !assets.length ? <div className="text-sm text-slate-500">No images yet — upload one.</div> : (
        <div className="grid grid-cols-5 gap-3">
          {assets.map((a) => (
            <button key={a.id} onClick={() => onPick(a)} className="rounded-lg border border-slate-200 p-1.5 hover:border-royal-500 hover:shadow-card text-left">
              <img src={fileUrl(`/api/assets/${a.id}/thumb?size=200`)} alt="" className="h-20 w-full object-contain bg-slate-50 rounded" loading="lazy" />
              <div className="text-[10px] text-slate-500 truncate mt-1">{a.name}</div>
            </button>
          ))}
        </div>
      )}
    </Modal>
  );
}
