import { Building2, Image as ImageIcon, Plus, Star, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Route } from "../App";
import { api, Branding, fileUrl } from "../api";
import { PdfViewer } from "../components/PdfViewer";
import { Badge, Button, Card, cx, errMsg, Field, SectionTitle, Spinner, TextInput, useDialogs, useToast } from "../components/ui";
import { AssetPicker } from "./Editor";
import { BrandingFields } from "./Templates";

function setP(o: any, path: string, v: any) {
  const c = structuredClone(o);
  const ks = path.split(".");
  let cur = c;
  for (const k of ks.slice(0, -1)) { cur[k] = cur[k] ?? {}; cur = cur[k]; }
  cur[ks[ks.length - 1]] = v;
  return c;
}

export default function BrandingPage(_: { route: Route }) {
  const toast = useToast();
  const { confirm } = useDialogs();
  const [list, setList] = useState<Branding[] | null>(null);
  const [cur, setCur] = useState<Branding | null>(null);
  const [dirty, setDirty] = useState(false);
  const [picker, setPicker] = useState<string | null>(null);
  const [prev, setPrev] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const n = useRef(0);
  const load = useCallback(async (select?: string) => {
    const l = await api<Branding[]>("/api/branding");
    setList(l);
    setCur(l.find((x) => x.id === select) || l.find((x) => x.is_default) || l[0] || null);
    setDirty(false);
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!cur) return;
    const k = ++n.current;
    const t = setTimeout(async () => {
      try {
        const d = await api("/api/templates/defaults");
        const r = await api("/api/templates/preview", { body: { config: { ...d.template, branding: cur.config, header: { ...d.template.header, style: "band" }, cover: { ...d.template.cover, style: "band" } } } });
        if (k === n.current) setPrev(fileUrl(r.url));
      } catch (e) { toast("error", errMsg(e)); }
    }, 700);
    return () => clearTimeout(t);
  }, [cur, toast]);

  const save = async () => {
    if (!cur) return;
    setSaving(true);
    try {
      const out = cur.id ? await api<Branding>(`/api/branding/${cur.id}`, { method: "PUT", body: { name: cur.name, config: cur.config } })
        : await api<Branding>("/api/branding", { body: { name: cur.name, config: cur.config } });
      toast("success", "Branding saved. Templates linked to this profile use it automatically.");
      await load(out.id);
    } catch (e) { toast("error", errMsg(e)); } finally { setSaving(false); }
  };
  const create = async () => {
    const d = await api("/api/templates/defaults");
    setCur({ id: "", name: "New branding profile", config: d.branding, is_default: 0 });
    setDirty(true);
  };
  if (!list) return <div className="flex justify-center py-24"><Spinner /></div>;
  return (
    <div>
      <SectionTitle title="Organization Branding" subtitle="Logos, colours, watermark and texts applied automatically to every page. Create a profile per school or exam board."
        actions={<Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={create}>New profile</Button>} />
      <div className="flex gap-5">
        <div className="w-60 shrink-0 space-y-2">
          {list.map((b) => (
            <button key={b.id} onClick={() => { setCur(b); setDirty(false); }} className={cx("w-full text-left rounded-xl border p-3 bg-white", cur?.id === b.id ? "border-royal-600 ring-2 ring-royal-100" : "border-slate-200 hover:border-slate-300")}>
              <div className="flex items-center gap-2">
                <div className="h-9 w-9 rounded-lg flex items-center justify-center overflow-hidden" style={{ background: b.config.colors.secondary }}>
                  {b.config.logo_asset ? <img src={fileUrl(`/api/assets/${b.config.logo_asset}/thumb?size=80`)} alt="" className="max-h-full" /> : <Building2 className="h-4 w-4 text-white" />}
                </div>
                <div className="min-w-0 flex-1"><div className="text-sm font-semibold text-navy-900 truncate">{b.name}</div><div className="text-[11px] text-slate-500 truncate">{b.config.org_name}</div></div>
              </div>
              {!!b.is_default && <Badge tone="navy" className="mt-2"><Star className="h-3 w-3" />Default</Badge>}
            </button>
          ))}
        </div>
        {cur && (
          <>
            <Card className="w-[420px] shrink-0 p-5 max-h-[calc(100vh-170px)] overflow-auto">
              <Field label="Profile name" className="mb-4"><TextInput value={cur.name} onChange={(e) => { setCur({ ...cur, name: e.target.value }); setDirty(true); }} /></Field>
              <BrandingFields cfg={cur.config} set={(p, v) => { setCur((c) => (c ? { ...c, config: setP(c.config, p, v) } : c)); setDirty(true); }}
                asset={(p, label) => (
                  <Field label={label}>
                    <div className="flex items-center gap-2">
                      <div className="h-12 w-20 rounded border border-slate-200 bg-slate-50 flex items-center justify-center overflow-hidden">
                        {p.split(".").reduce((a: any, k) => a?.[k], cur.config) ? <img src={fileUrl(`/api/assets/${p.split(".").reduce((a: any, k) => a?.[k], cur.config)}/thumb?size=160`)} alt="" className="max-h-full max-w-full" /> : <ImageIcon className="h-5 w-5 text-slate-300" />}
                      </div>
                      <Button size="sm" onClick={() => setPicker(p)}>Choose…</Button>
                    </div>
                  </Field>
                )} />
              <div className="flex gap-2 mt-6 sticky bottom-0 bg-white pt-3">
                <Button variant="primary" loading={saving} disabled={!dirty && !!cur.id} onClick={save}>Save profile</Button>
                {cur.id && !cur.is_default && <Button onClick={async () => { await api(`/api/branding/${cur.id}/default`, { method: "POST" }); toast("success", "Default profile updated"); load(cur.id); }}>Set as default</Button>}
                {cur.id && !cur.is_default && <Button variant="ghost" icon={<Trash2 className="h-4 w-4 text-brandred-600" />} onClick={async () => {
                  if (await confirm({ title: "Delete branding profile?", danger: true, confirmText: "Delete", message: <>“{cur.name}” will be deleted. Templates using it must be switched first.</> })) {
                    try { await api(`/api/branding/${cur.id}`, { method: "DELETE" }); toast("success", "Deleted"); load(); } catch (e) { toast("error", errMsg(e)); }
                  }
                }} />}
              </div>
            </Card>
            <div className="flex-1 min-w-0 h-[calc(100vh-170px)]">{prev ? <PdfViewer url={prev} showThumbs={false} /> : <div className="flex justify-center py-20"><Spinner /></div>}</div>
          </>
        )}
      </div>
      <AssetPicker open={!!picker} onClose={() => setPicker(null)} kinds="logo,image,watermark" onPick={(a) => {
        if (picker && cur) { setCur({ ...cur, config: setP(cur.config, picker, a.id) }); setDirty(true); }
        setPicker(null);
      }} />
    </div>
  );
}
