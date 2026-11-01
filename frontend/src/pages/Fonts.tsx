import { Trash2, Type } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import type { Route } from "../App";
import { api, fontUrl, upload } from "../api";
import { Badge, Card, Dropzone, errMsg, Field, SectionTitle, Select, Spinner, TextInput, useDialogs, useToast } from "../components/ui";

type Fam = { family: string; source: string; embeddable: boolean };
type Installed = { id: string; family: string; style: string; path: string };
const SAMPLE = "Oʻquvchi “kitob” soʻzini oʻqidi — The quick brown fox jumps over the lazy dog. Gʻalaba! 1234567890";
const loaded = new Set<string>();

function useFace(family: string) {
  const [ok, setOk] = useState(loaded.has(family));
  useEffect(() => {
    if (loaded.has(family)) { setOk(true); return; }
    const styles: [string, string, string][] = [["regular", "normal", "400"], ["bold", "normal", "700"], ["italic", "italic", "400"]];
    Promise.all(styles.map(([st, style, weight]) => new FontFace(`ptd-${family}`, `url("${fontUrl(family, st)}")`, { style, weight }).load()
      .then((f) => { (document.fonts as any).add(f); }).catch(() => {})))
      .then(() => { loaded.add(family); setOk(true); });
  }, [family]);
  return ok;
}

function FontCard({ f, installed, onDelete }: { f: Fam; installed: Installed[]; onDelete: (i: Installed) => void }) {
  const ok = useFace(f.family);
  return (
    <Card className="p-5">
      <div className="flex items-center gap-2 mb-3">
        <div className="font-semibold text-navy-900">{f.family}</div>
        <Badge tone={f.source === "custom" ? "blue" : f.source.startsWith("substituted") ? "amber" : "slate"}>{f.source}</Badge>
        {f.embeddable ? <Badge tone="green">embedded in PDFs</Badge> : <Badge tone="red">cannot be embedded</Badge>}
      </div>
      {ok ? (
        <div style={{ fontFamily: `"ptd-${f.family}"` }} className="space-y-1 text-navy-900">
          <div className="text-[22px] leading-snug">{SAMPLE}</div>
          <div className="text-[15px] font-bold">Bold — Toʻgʻri javobni tanlang.</div>
          <div className="text-[15px] italic">Italic — Choose the correct answer.</div>
        </div>
      ) : <Spinner />}
      {installed.length > 0 && (
        <div className="flex flex-wrap gap-2 mt-3">
          {installed.map((i) => (
            <span key={i.id} className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 pl-2.5 pr-1 py-0.5 text-xs text-slate-700">
              {i.style}<button className="p-0.5 rounded-full hover:bg-white text-brandred-600" title="Remove" onClick={() => onDelete(i)}><Trash2 className="h-3 w-3" /></button>
            </span>
          ))}
        </div>
      )}
    </Card>
  );
}

export default function Fonts(_: { route: Route }) {
  const toast = useToast();
  const { confirm } = useDialogs();
  const [data, setData] = useState<{ families: Fam[]; installed: Installed[] } | null>(null);
  const [family, setFamily] = useState("");
  const [style, setStyle] = useState("");
  const load = useCallback(() => api("/api/fonts").then(setData), []);
  useEffect(() => { load(); }, [load]);
  const onFiles = async (files: File[]) => {
    for (const f of files) {
      try { const r = await upload("/api/fonts", { family: family || undefined, style: style || undefined }, [f]); toast("success", `Installed ${r.family} (${r.style})`); }
      catch (e) { toast("error", `${f.name}: ${errMsg(e)}`); }
    }
    load();
  };
  if (!data) return <div className="flex justify-center py-24"><Spinner /></div>;
  return (
    <div>
      <SectionTitle title="Font Manager" subtitle="Fonts are embedded into every PDF so Uzbek Latin (oʻ, gʻ), curly quotes and long dashes always print correctly." />
      <Card className="p-5 mb-6">
        <div className="grid grid-cols-3 gap-4 items-end">
          <div className="col-span-1 space-y-3">
            <Field label="Family name (optional)" hint="Leave empty to use the name stored in the font file"><TextInput value={family} onChange={(e) => setFamily(e.target.value)} placeholder="e.g. School Serif" /></Field>
            <Field label="Style (optional)"><Select value={style} onChange={setStyle} options={[{ value: "", label: "Detect from file" }, { value: "regular", label: "Regular" }, { value: "bold", label: "Bold" }, { value: "italic", label: "Italic" }, { value: "bolditalic", label: "Bold Italic" }]} /></Field>
          </div>
          <div className="col-span-2"><Dropzone compact multiple accept=".ttf,.otf" onFiles={onFiles} title="Install TTF / OTF fonts" subtitle="Upload Regular, Bold, Italic and Bold Italic files of a family" /></div>
        </div>
        <div className="text-xs text-slate-500 mt-3">Fonts whose licence forbids embedding are rejected. OTF (CFF) fonts are converted to TrueType automatically.</div>
      </Card>
      <div className="grid grid-cols-2 gap-5">
        {data.families.map((f) => (
          <FontCard key={f.family} f={f} installed={data.installed.filter((i) => i.family === f.family)}
            onDelete={async (i) => {
              if (await confirm({ title: "Remove font file?", danger: true, confirmText: "Remove", message: <>{i.family} {i.style} will be removed. Templates using it fall back to DejaVu Sans with a warning.</> })) {
                try { await api(`/api/fonts/${i.id}`, { method: "DELETE" }); load(); } catch (e) { toast("error", errMsg(e)); }
              }
            }} />
        ))}
      </div>
      {!data.installed.length && <div className="text-sm text-slate-400 mt-6 flex items-center gap-2"><Type className="h-4 w-4" />No custom fonts installed yet.</div>}
    </div>
  );
}
