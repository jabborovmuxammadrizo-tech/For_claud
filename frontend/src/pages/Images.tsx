import { Crop, FlipHorizontal, FlipVertical, Image as ImageIcon, RotateCcw, RotateCw, Trash2 } from "lucide-react";
import React, { useCallback, useEffect, useRef, useState } from "react";
import type { Route } from "../App";
import { api, Asset, fileUrl, upload } from "../api";
import { Badge, Button, Card, ColorInput, cx, Dropzone, EmptyState, errMsg, Field, fmtBytes, NumberInput, SectionTitle, Select, Slider, Spinner, TextInput, Toggle, useDialogs, useToast } from "../components/ui";

type CropRect = { x: number; y: number; w: number; h: number };
const KINDS = [["", "All"], ["image", "Images"], ["logo", "Logos"], ["watermark", "Watermarks"], ["background", "Backgrounds"], ["extracted", "Extracted from documents"]];

export default function ImageLibrary(_: { route: Route }) {
  const toast = useToast();
  const { confirm } = useDialogs();
  const [assets, setAssets] = useState<Asset[] | null>(null);
  const [kind, setKind] = useState("");
  const [sel, setSel] = useState<Asset | null>(null);
  const load = useCallback(async () => {
    const a = await api<Asset[]>(`/api/assets${kind ? `?kind=${kind}` : ""}`);
    setAssets(a);
    setSel((s) => (s ? a.find((x) => x.id === s.id) || null : null));
  }, [kind]);
  useEffect(() => { load(); }, [load]);
  const onFiles = async (files: File[]) => {
    try {
      let last: Asset | null = null;
      for (const f of files) last = await upload("/api/assets", { kind: kind && kind !== "extracted" ? kind : "image" }, [f]);
      toast("success", `${files.length} image(s) added`);
      await load();
      if (last) setSel(last);
    } catch (e) { toast("error", errMsg(e)); }
  };
  return (
    <div>
      <SectionTitle title="Image Library" subtitle="Logos, pictures, maps and images extracted from your documents. Edits always create a new copy; originals stay untouched." />
      <div className="flex gap-2 mb-5 flex-wrap">
        {KINDS.map(([k, l]) => <button key={k} onClick={() => setKind(k)} className={cx("px-3 py-1.5 rounded-full text-sm", kind === k ? "bg-navy-900 text-white" : "bg-white border border-slate-200 text-slate-600")}>{l}</button>)}
      </div>
      <div className="flex gap-6">
        <div className="flex-1 min-w-0">
          <Dropzone compact multiple accept=".png,.jpg,.jpeg,.svg,.gif,.bmp,.tif,.tiff,.webp" onFiles={onFiles} title="Upload images" subtitle="PNG (incl. transparent), JPG, SVG, GIF, BMP, TIFF, WEBP" />
          {!assets ? <Spinner className="mt-6" /> : !assets.length ? <EmptyState icon={<ImageIcon className="h-6 w-6" />} title="No images here yet" text="Upload logos and pictures, or import a document to extract its images." /> : (
            <div className="grid grid-cols-4 xl:grid-cols-5 gap-3 mt-5">
              {assets.map((a) => (
                <button key={a.id} onClick={() => setSel(a)} className={cx("rounded-xl bg-white border p-2 text-left transition", sel?.id === a.id ? "border-royal-600 ring-2 ring-royal-100" : "border-slate-200 hover:border-slate-300 hover:shadow-card")}>
                  <div className="h-28 rounded-lg bg-[conic-gradient(#f1f5f9_25%,#fff_0_50%,#f1f5f9_0_75%,#fff_0)] bg-[length:16px_16px] flex items-center justify-center overflow-hidden">
                    <img src={fileUrl(`/api/assets/${a.id}/thumb?size=260`)} alt="" className="max-h-full max-w-full object-contain" loading="lazy" />
                  </div>
                  <div className="text-xs font-medium text-navy-900 truncate mt-1.5">{a.name}</div>
                  <div className="text-[10px] text-slate-500 flex justify-between"><span>{a.width}×{a.height}</span><span>{a.kind}</span></div>
                </button>
              ))}
            </div>
          )}
        </div>
        {sel && <ImageEditor key={sel.id} asset={sel} onSaved={async (a) => { await load(); setSel(a); }} onDeleted={async () => { setSel(null); await load(); }} confirm={confirm} />}
      </div>
    </div>
  );
}

function ImageEditor({ asset, onSaved, onDeleted, confirm }: { asset: Asset; onSaved: (a: Asset) => void; onDeleted: () => void; confirm: ReturnType<typeof useDialogs>["confirm"] }) {
  const toast = useToast();
  const [crop, setCrop] = useState<CropRect | null>(null);
  const [cropping, setCropping] = useState(false);
  const [rotate, setRotate] = useState(0);
  const [flipH, setFlipH] = useState(false);
  const [flipV, setFlipV] = useState(false);
  const [opacity, setOpacity] = useState(1);
  const [width, setWidth] = useState<number | null>(null);
  const [bg, setBg] = useState<string | null>(null);
  const [name, setName] = useState(asset.name.replace(/\.[^.]+$/, ""));
  const [saving, setSaving] = useState(false);
  const [info, setInfo] = useState<Asset | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const svg = asset.path.toLowerCase().endsWith(".svg");
  useEffect(() => { api<Asset>(`/api/assets/${asset.id}`).then(setInfo); }, [asset.id]);

  const startCrop = (e: React.MouseEvent) => {
    if (!cropping || !box.current) return;
    const r = box.current.getBoundingClientRect();
    const sx = (e.clientX - r.left) / r.width, sy = (e.clientY - r.top) / r.height;
    const inside = crop && sx > crop.x && sx < crop.x + crop.w && sy > crop.y && sy < crop.y + crop.h;
    const orig = crop;
    const move = (ev: MouseEvent) => {
      const cx_ = Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width)), cy_ = Math.max(0, Math.min(1, (ev.clientY - r.top) / r.height));
      if (inside && orig) {
        const nx = Math.max(0, Math.min(1 - orig.w, orig.x + cx_ - sx)), ny = Math.max(0, Math.min(1 - orig.h, orig.y + cy_ - sy));
        setCrop({ ...orig, x: nx, y: ny });
      } else {
        setCrop({ x: Math.min(sx, cx_), y: Math.min(sy, cy_), w: Math.abs(cx_ - sx), h: Math.abs(cy_ - sy) });
      }
    };
    const up = () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); };
    window.addEventListener("mousemove", move); window.addEventListener("mouseup", up);
  };
  const changed = !!crop || rotate !== 0 || flipH || flipV || opacity < 1 || !!width || !!bg;
  const save = async () => {
    setSaving(true);
    try {
      const ops: Record<string, unknown> = {};
      if (crop && crop.w > 0.01 && crop.h > 0.01) ops.crop = crop;
      if (rotate) ops.rotate = rotate;
      if (flipH) ops.flip_h = true;
      if (flipV) ops.flip_v = true;
      if (width) ops.resize = { width };
      if (opacity < 1) ops.opacity = opacity;
      if (bg) ops.background = bg;
      const a = await api<Asset>(`/api/assets/${asset.id}/edit`, { body: { ops, name: name || `${asset.name} (edited)` } });
      toast("success", "Edited copy saved — the original image is unchanged.");
      onSaved(a);
    } catch (e) { toast("error", errMsg(e)); } finally { setSaving(false); }
  };
  return (
    <Card className="w-[420px] shrink-0 p-5 self-start sticky top-0 max-h-[calc(100vh-120px)] overflow-auto">
      <div className="flex items-center justify-between mb-3">
        <div className="font-semibold text-navy-900 truncate">{asset.name}</div>
        <Badge>{asset.kind}</Badge>
      </div>
      <div className="rounded-lg bg-[conic-gradient(#f1f5f9_25%,#fff_0_50%,#f1f5f9_0_75%,#fff_0)] bg-[length:16px_16px] p-3 flex items-center justify-center">
        <div ref={box} className={cx("relative inline-block select-none", cropping && "cursor-crosshair")} onMouseDown={startCrop}
          style={{ transform: `rotate(${rotate}deg) scale(${flipH ? -1 : 1}, ${flipV ? -1 : 1})` }}>
          <img src={fileUrl(`/api/assets/${asset.id}/file`)} alt="" draggable={false} className="max-h-72 max-w-full block"
            style={{ opacity, background: bg || undefined }} />
          {crop && (
            <div className="absolute border-2 border-royal-600 bg-royal-500/10 shadow-[0_0_0_9999px_rgba(15,31,75,.45)]"
              style={{ left: `${crop.x * 100}%`, top: `${crop.y * 100}%`, width: `${crop.w * 100}%`, height: `${crop.h * 100}%` }} />
          )}
        </div>
      </div>
      <div className="text-[11px] text-slate-500 mt-2">{asset.width}×{asset.height}px · {fmtBytes(asset.size)}{asset.dpi ? ` · ${asset.dpi} dpi` : ""}{info?.used_by?.length ? ` · used by ${info.used_by.join(", ")}` : ""}</div>
      {svg ? <div className="text-sm text-slate-500 mt-4">SVG images are vector graphics: they print sharply at any size and need no editing.</div> : (
        <div className="space-y-4 mt-4">
          <div className="flex flex-wrap gap-1.5">
            <Button size="sm" variant={cropping ? "primary" : "secondary"} icon={<Crop className="h-4 w-4" />} disabled={!!rotate || flipH || flipV}
              title={rotate || flipH || flipV ? "Crop first, then rotate or flip (the crop is applied to the original orientation)" : "Crop"}
              onClick={() => { setCropping(!cropping); if (!crop) setCrop({ x: 0.1, y: 0.1, w: 0.8, h: 0.8 }); }}>{cropping ? "Cropping…" : "Crop"}</Button>
            {crop && <Button size="sm" variant="ghost" onClick={() => { setCrop(null); setCropping(false); }}>Clear crop</Button>}
            <Button size="sm" icon={<RotateCcw className="h-4 w-4" />} onClick={() => { setCropping(false); setRotate((r) => (r - 90 + 360) % 360); }} title="Rotate left" />
            <Button size="sm" icon={<RotateCw className="h-4 w-4" />} onClick={() => { setCropping(false); setRotate((r) => (r + 90) % 360); }} title="Rotate right" />
            <Button size="sm" variant={flipH ? "primary" : "secondary"} icon={<FlipHorizontal className="h-4 w-4" />} onClick={() => setFlipH(!flipH)} title="Flip horizontally" />
            <Button size="sm" variant={flipV ? "primary" : "secondary"} icon={<FlipVertical className="h-4 w-4" />} onClick={() => setFlipV(!flipV)} title="Flip vertically" />
          </div>
          {cropping && <div className="text-xs text-slate-500">Drag on the image to draw the crop area; drag inside it to move it.</div>}
          <Field label="Transparency"><Slider value={opacity} min={0.05} max={1} step={0.05} onChange={setOpacity} format={(v) => `${Math.round(v * 100)}%`} /></Field>
          <Field label="Resize width (px, keeps aspect ratio)"><NumberInput value={width} min={8} max={12000} placeholder={`${asset.width}`} onChange={setWidth} /></Field>
          <Toggle label="Fill transparent background" checked={!!bg} onChange={(v) => setBg(v ? "#FFFFFF" : null)} />
          {bg && <ColorInput value={bg} onChange={setBg} />}
          <Field label="Name of the edited copy"><TextInput value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Button variant="primary" className="w-full" disabled={!changed} loading={saving} onClick={save}>Save edited copy</Button>
        </div>
      )}
      <div className="border-t border-slate-100 mt-5 pt-4 space-y-3">
        <Field label="Use this image as">
          <Select value={asset.kind === "extracted" ? "image" : asset.kind} onChange={async (k) => { try { const a = await api<Asset>(`/api/assets/${asset.id}`, { method: "PATCH", body: { kind: k } }); onSaved(a); } catch (e) { toast("error", errMsg(e)); } }}
            options={[{ value: "image", label: "Picture" }, { value: "logo", label: "Logo" }, { value: "watermark", label: "Watermark" }, { value: "background", label: "Page background" }]} />
        </Field>
        <Button variant="ghost" className="text-brandred-600" icon={<Trash2 className="h-4 w-4" />} onClick={async () => {
          if (await confirm({ title: "Delete image?", danger: true, confirmText: "Delete", message: <>“{asset.name}” will be deleted. Images used by templates or branding cannot be deleted. Documents that use it will show a missing-image warning.</> })) {
            try { await api(`/api/assets/${asset.id}`, { method: "DELETE" }); toast("success", "Image deleted"); onDeleted(); } catch (e) { toast("error", errMsg(e)); }
          }
        }}>Delete image</Button>
      </div>
    </Card>
  );
}
