import * as pdfjs from "pdfjs-dist";
import type { PDFDocumentProxy, RenderTask } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { ChevronLeft, ChevronRight, Maximize, MoveHorizontal, ZoomIn, ZoomOut } from "lucide-react";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { cx, Spinner } from "./ui";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

export function usePdf(url: string | null | undefined) {
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!url) { setDoc(null); return; }
    let cancelled = false;
    const task = pdfjs.getDocument({ url, isEvalSupported: false });
    setError(null);
    task.promise.then((d) => { if (!cancelled) setDoc(d); else d.destroy(); }, (e) => { if (!cancelled) setError(String(e?.message || e)); });
    return () => { cancelled = true; task.destroy(); };
  }, [url]);
  return { doc, error };
}

export function PdfPage({ doc, pageNumber, width, className, children, onSize }: {
  doc: PDFDocumentProxy; pageNumber: number; width: number; className?: string; children?: React.ReactNode;
  onSize?: (s: { width: number; height: number; scale: number }) => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  useEffect(() => {
    let task: RenderTask | null = null;
    let cancelled = false;
    doc.getPage(pageNumber).then((page) => {
      if (cancelled) return;
      const base = page.getViewport({ scale: 1 });
      const scale = width / base.width;
      const vp = page.getViewport({ scale });
      const dpr = Math.min(window.devicePixelRatio || 1, 2.5);
      const c = canvas.current;
      if (!c) return;
      c.width = Math.floor(vp.width * dpr);
      c.height = Math.floor(vp.height * dpr);
      c.style.width = `${vp.width}px`;
      c.style.height = `${vp.height}px`;
      setSize({ w: vp.width, h: vp.height });
      onSize?.({ width: vp.width, height: vp.height, scale });
      const ctx = c.getContext("2d")!;
      task = page.render({ canvasContext: ctx, viewport: vp, transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined });
      task.promise.catch(() => { /* cancelled */ });
    });
    return () => { cancelled = true; task?.cancel(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc, pageNumber, width]);
  return (
    <div className={cx("relative bg-white shadow-card", className)} style={size ? { width: size.w, height: size.h } : { width, height: width * 1.414 }}>
      <canvas ref={canvas} className="block" />
      {children}
    </div>
  );
}

function LazyPage(props: React.ComponentProps<typeof PdfPage>) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(props.pageNumber <= 2);
  useEffect(() => {
    const el = ref.current;
    if (!el || visible) return;
    const io = new IntersectionObserver((e) => { if (e[0].isIntersecting) { setVisible(true); io.disconnect(); } }, { rootMargin: "800px" });
    io.observe(el);
    return () => io.disconnect();
  }, [visible]);
  return <div ref={ref} data-page={props.pageNumber}>{visible ? <PdfPage {...props} /> : <div className="bg-white shadow-card" style={{ width: props.width, height: props.width * 1.414 }} />}</div>;
}

export function PdfViewer({ url, className, initialPage = 1, showThumbs = true }: { url: string; className?: string; initialPage?: number; showThumbs?: boolean }) {
  const { doc, error } = usePdf(url);
  const scroller = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState<number | "width" | "page">("width");
  const [page, setPage] = useState(initialPage);
  const [box, setBox] = useState({ w: 800, h: 600 });
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setBox({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const width = useMemo(() => {
    if (zoom === "width") return Math.max(320, box.w - 64);
    if (zoom === "page") return Math.max(240, (box.h - 48) / 1.414);
    return 595 * zoom;
  }, [zoom, box]);
  const n = doc?.numPages || 0;
  const go = (p: number) => {
    const t = Math.max(1, Math.min(n, p));
    setPage(t);
    scroller.current?.querySelector(`[data-page="${t}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  useEffect(() => { if (doc && initialPage > 1) setTimeout(() => go(initialPage), 200); /* eslint-disable-next-line */ }, [doc]);
  const onScroll = () => {
    const el = scroller.current;
    if (!el) return;
    const pages = Array.from(el.querySelectorAll<HTMLElement>("[data-page]"));
    const top = el.scrollTop + 60;
    let cur = 1;
    for (const p of pages) if (p.offsetTop <= top) cur = Number(p.dataset.page);
    setPage(cur);
  };
  const numericZoom = typeof zoom === "number" ? zoom : width / 595;
  return (
    <div className={cx("flex h-full min-h-0 bg-slate-100 rounded-xl overflow-hidden border border-slate-200", className)}>
      {showThumbs && doc && (
        <div className="w-36 shrink-0 overflow-auto border-r border-slate-200 bg-white p-2 space-y-2">
          {Array.from({ length: n }, (_, i) => (
            <button key={i} onClick={() => go(i + 1)} className={cx("block w-full rounded-md p-1 border-2", page === i + 1 ? "border-royal-500" : "border-transparent hover:border-slate-200")}>
              <LazyPage doc={doc} pageNumber={i + 1} width={108} />
              <div className="text-[10px] text-slate-500 mt-1">{i + 1}</div>
            </button>
          ))}
        </div>
      )}
      <div className="flex-1 flex flex-col min-w-0">
        <div className="flex items-center gap-1 px-3 py-2 border-b border-slate-200 bg-white text-sm">
          <button className="p-1.5 rounded hover:bg-slate-100 disabled:opacity-40" onClick={() => go(page - 1)} disabled={page <= 1} aria-label="Previous page"><ChevronLeft className="h-4 w-4" /></button>
          <span className="tabular-nums text-slate-600 w-24 text-center">Page {page} / {n || "…"}</span>
          <button className="p-1.5 rounded hover:bg-slate-100 disabled:opacity-40" onClick={() => go(page + 1)} disabled={page >= n} aria-label="Next page"><ChevronRight className="h-4 w-4" /></button>
          <div className="mx-2 h-5 w-px bg-slate-200" />
          <button className="p-1.5 rounded hover:bg-slate-100" onClick={() => setZoom(Math.max(0.3, numericZoom - 0.15))} aria-label="Zoom out"><ZoomOut className="h-4 w-4" /></button>
          <span className="w-12 text-center tabular-nums text-slate-600">{Math.round(numericZoom * 100)}%</span>
          <button className="p-1.5 rounded hover:bg-slate-100" onClick={() => setZoom(Math.min(4, numericZoom + 0.15))} aria-label="Zoom in"><ZoomIn className="h-4 w-4" /></button>
          <button className={cx("ml-1 px-2 py-1 rounded text-xs flex items-center gap-1", zoom === "width" ? "bg-royal-50 text-royal-700" : "hover:bg-slate-100")} onClick={() => setZoom("width")}><MoveHorizontal className="h-3.5 w-3.5" />Fit width</button>
          <button className={cx("px-2 py-1 rounded text-xs flex items-center gap-1", zoom === "page" ? "bg-royal-50 text-royal-700" : "hover:bg-slate-100")} onClick={() => setZoom("page")}><Maximize className="h-3.5 w-3.5" />Fit page</button>
        </div>
        <div ref={scroller} onScroll={onScroll} className="flex-1 overflow-auto p-6">
          {error && <div className="text-brandred-600 text-sm">Could not open the PDF: {error}</div>}
          {!doc && !error && <div className="flex justify-center py-20"><Spinner /></div>}
          {doc && (
            <div className="flex flex-col items-center gap-6">
              {Array.from({ length: n }, (_, i) => <LazyPage key={`${url}-${i}`} doc={doc} pageNumber={i + 1} width={width} />)}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
