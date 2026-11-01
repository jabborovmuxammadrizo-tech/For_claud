import { Download } from "lucide-react";
import { useState } from "react";
import { api, Block, saveFile } from "../api";
import { Button, errMsg, Field, Modal, Select, TextInput, Toggle, useToast } from "./ui";

/** Custom export: PDF variants, selected pages/sections, page images, structure JSON, template file. */
export function ExportDialog({ open, onClose, documentId, templateId, title, blocks }: {
  open: boolean; onClose: () => void; documentId: string; templateId: string; title: string; blocks: Block[];
}) {
  const toast = useToast();
  const [kind, setKind] = useState("pdf");
  const [quality, setQuality] = useState("print");
  const [gray, setGray] = useState(false);
  const [pages, setPages] = useState("");
  const [sections, setSections] = useState<string[]>([]);
  const [dpi, setDpi] = useState("150");
  const [busy, setBusy] = useState(false);
  const secs = blocks.filter((b) => b.type === "section");
  const parsePages = (): number[] | undefined => {
    if (!pages.trim()) return undefined;
    const out: number[] = [];
    for (const part of pages.split(",")) {
      const m = part.trim().match(/^(\d+)(?:\s*-\s*(\d+))?$/);
      if (!m) throw new Error(`Invalid page range “${part.trim()}”. Use e.g. 1-3, 5`);
      const a = Number(m[1]), b = Number(m[2] || m[1]);
      for (let i = Math.min(a, b); i <= Math.max(a, b); i++) out.push(i);
    }
    return out;
  };
  const run = async () => {
    setBusy(true);
    try {
      const recs = await api<{ id: string; path: string }[]>(`/api/documents/${documentId}/export`, {
        body: { template_id: templateId, kind, quality, grayscale: gray, pages: parsePages(), sections: sections.length ? sections : undefined, dpi: Number(dpi) },
      });
      const name = recs[0].path.split(/[\\/]/).pop() || `${title}.pdf`;
      const saved = await saveFile(`/api/exports/${recs[0].id}/file`, name);
      if (saved) { toast("success", `Exported: ${name}`); onClose(); }
    } catch (e) { toast("error", errMsg(e)); } finally { setBusy(false); }
  };
  const pdfLike = kind === "pdf" || kind === "png" || kind === "jpeg";
  return (
    <Modal open={open} onClose={onClose} title="Export" footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} icon={<Download className="h-4 w-4" />} onClick={run}>Export</Button></>}>
      <div className="space-y-4">
        <Field label="Format">
          <Select value={kind} onChange={setKind} options={[{ value: "pdf", label: "PDF" }, { value: "png", label: "PNG page images (ZIP)" }, { value: "jpeg", label: "JPEG page images (ZIP)" },
            { value: "json", label: "Document structure (JSON)" }, { value: "template", label: "Reusable template file" }]} />
        </Field>
        {kind === "pdf" && (
          <Field label="Quality">
            <Select value={quality} onChange={setQuality} options={[{ value: "print", label: "High-quality print (300 dpi images)" }, { value: "standard", label: "Standard (200 dpi)" }, { value: "compressed", label: "Compressed (smallest file)" }]} />
          </Field>
        )}
        {kind !== "pdf" && pdfLike && <Field label="Resolution (dpi)"><Select value={dpi} onChange={setDpi} options={["96", "150", "200", "300"].map((v) => ({ value: v, label: `${v} dpi` }))} /></Field>}
        {pdfLike && <>
          <Toggle label="Grayscale" checked={gray} onChange={setGray} />
          <Field label="Pages (empty = whole document)" hint="e.g. 1-3, 5"><TextInput value={pages} onChange={(e) => setPages(e.target.value)} placeholder="all pages" /></Field>
          {secs.length > 0 && (
            <Field label="Only these sections (optional)">
              <div className="max-h-40 overflow-auto rounded-lg border border-slate-200 divide-y divide-slate-50">
                {secs.map((s) => (
                  <label key={s.id} className="flex items-center gap-2 px-3 py-1.5 text-sm cursor-pointer">
                    <input type="checkbox" checked={sections.includes(s.id)} onChange={(e) => setSections(e.target.checked ? [...sections, s.id] : sections.filter((x) => x !== s.id))} />
                    {s.title}
                  </label>
                ))}
              </div>
            </Field>
          )}
        </>}
      </div>
    </Modal>
  );
}
