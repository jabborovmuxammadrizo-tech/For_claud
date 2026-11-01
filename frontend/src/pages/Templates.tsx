import { ArrowLeft, Copy, Download, Eye, Image as ImageIcon, Lock, Pencil, Plus, Star, Trash2, Upload } from "lucide-react";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { navigate, Route } from "../App";
import { api, Branding, fileUrl, Issue, saveFile, Template, upload } from "../api";
import { IssueList } from "../components/job";
import { PdfViewer } from "../components/PdfViewer";
import {
  Badge, Button, Card, ColorInput, cx, errMsg, Field, Modal, NumberInput, SectionTitle, Select, Slider, Spinner, TextArea, TextInput, Toggle, useDialogs, useToast,
} from "../components/ui";
import { AssetPicker } from "./Editor";

const CATEGORIES = [["standard", "Standard examination"], ["beginner", "Beginner"], ["elementary", "Elementary"], ["pre_intermediate", "Pre-Intermediate"],
  ["general_english", "General English"], ["certificate", "Certificate examination"], ["listening", "Listening test"], ["reading", "Reading test"], ["custom", "Custom examination"]];

export default function TemplatesPage({ route }: { route: Route }) {
  if (route.id) return <TemplateEditor key={route.id} id={route.id} />;
  return <TemplateLibrary />;
}

function TemplateLibrary() {
  const toast = useToast();
  const { confirm, prompt } = useDialogs();
  const [list, setList] = useState<Template[] | null>(null);
  const [preview, setPreview] = useState<{ name: string; url: string } | null>(null);
  const [cat, setCat] = useState("");
  const load = useCallback(() => api<Template[]>("/api/templates").then(setList), []);
  useEffect(() => { load(); }, [load]);
  const run = async (fn: () => Promise<unknown>, ok?: string) => { try { await fn(); if (ok) toast("success", ok); await load(); } catch (e) { toast("error", errMsg(e)); } };
  const showPreview = async (t: Template) => {
    try { const r = await api("/api/templates/preview", { body: { config: t.config } }); setPreview({ name: t.name, url: fileUrl(r.url) }); } catch (e) { toast("error", errMsg(e)); }
  };
  const imp = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (f) run(() => upload("/api/templates/import", {}, [f]), "Template imported");
  };
  const shown = (list || []).filter((t) => !cat || t.category === cat);
  return (
    <div>
      <SectionTitle title="Templates" subtitle="Reusable designs: branding, fonts, colours, page layout, question styles, pagination and export preferences."
        actions={<>
          <label className="inline-flex h-10 items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 text-sm font-medium cursor-pointer hover:bg-slate-50"><Upload className="h-4 w-4" />Import<input type="file" accept=".json" className="hidden" onChange={imp} /></label>
          <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => navigate("templates/new")}>New template</Button>
        </>} />
      <div className="flex gap-2 mb-5 flex-wrap">
        <button className={cx("px-3 py-1.5 rounded-full text-sm", !cat ? "bg-navy-900 text-white" : "bg-white border border-slate-200 text-slate-600")} onClick={() => setCat("")}>All</button>
        {CATEGORIES.map(([k, l]) => <button key={k} className={cx("px-3 py-1.5 rounded-full text-sm", cat === k ? "bg-navy-900 text-white" : "bg-white border border-slate-200 text-slate-600 hover:border-slate-300")} onClick={() => setCat(k)}>{l}</button>)}
      </div>
      {!list ? <Spinner /> : (
        <div className="grid grid-cols-3 gap-5">
          {shown.map((t) => {
            const c = t.config.branding.colors;
            return (
              <Card key={t.id} className="overflow-hidden flex flex-col">
                <div className="h-28 relative" style={{ background: `linear-gradient(135deg, ${c.secondary}, ${c.primary})` }}>
                  <div className="absolute inset-x-0 bottom-0 h-1.5" style={{ background: c.accent }} />
                  <div className="absolute left-5 top-5 bg-white/95 rounded-md shadow w-20 h-24 p-1.5 space-y-1">
                    <div className="h-2 rounded-sm" style={{ background: c.primary }} />
                    {[0, 1, 2, 3, 4].map((i) => <div key={i} className="h-1 rounded-sm bg-slate-200" style={{ width: `${90 - i * 9}%` }} />)}
                  </div>
                  <div className="absolute right-4 top-4 flex gap-1.5">
                    {!!t.is_default && <Badge tone="blue"><Star className="h-3 w-3" />Default</Badge>}
                    {!!t.builtin && <Badge className="bg-white/90"><Lock className="h-3 w-3" />Built-in</Badge>}
                  </div>
                </div>
                <div className="p-4 flex-1 flex flex-col">
                  <div className="font-semibold text-navy-900">{t.name}</div>
                  <div className="text-xs text-slate-500 mt-1 flex-1">{t.description}</div>
                  <div className="text-[11px] text-slate-400 mt-2">{CATEGORIES.find((x) => x[0] === t.category)?.[1] || t.category} · {t.config.fonts.body} {t.config.fonts.body_size}pt · {t.config.pagination.density}</div>
                  <div className="flex flex-wrap gap-1 mt-3">
                    <Button size="sm" icon={<Eye className="h-3.5 w-3.5" />} onClick={() => showPreview(t)}>Preview</Button>
                    <Button size="sm" icon={t.builtin ? <Eye className="h-3.5 w-3.5" /> : <Pencil className="h-3.5 w-3.5" />} onClick={() => navigate(`templates/${t.id}`)}>{t.builtin ? "View" : "Edit"}</Button>
                    <Button size="sm" variant="ghost" title="Duplicate" icon={<Copy className="h-3.5 w-3.5" />} onClick={async () => {
                      const n = await prompt({ title: "Duplicate template", label: "Name of the copy", initial: `${t.name} (copy)` });
                      if (n) run(() => api(`/api/templates/${t.id}/duplicate`, { body: { name: n } }), "Template duplicated");
                    }} />
                    {!t.builtin && <Button size="sm" variant="ghost" title="Rename" icon={<Pencil className="h-3.5 w-3.5" />} onClick={async () => {
                      const n = await prompt({ title: "Rename template", label: "Template name", initial: t.name });
                      if (n) run(() => api(`/api/templates/${t.id}`, { method: "PUT", body: { ...t.config, name: n } }), "Renamed");
                    }} />}
                    <Button size="sm" variant="ghost" title="Export" icon={<Download className="h-3.5 w-3.5" />} onClick={() => saveFile(`/api/templates/${t.id}/export`, `${t.name}.ptdtemplate.json`).catch((e) => toast("error", errMsg(e)))} />
                    {!t.is_default && <Button size="sm" variant="ghost" title="Set as default" icon={<Star className="h-3.5 w-3.5" />} onClick={() => run(() => api(`/api/templates/${t.id}/default`, { method: "POST" }), `“${t.name}” is now the default`)} />}
                    {!t.is_default && <Button size="sm" variant="ghost" title="Delete" icon={<Trash2 className="h-3.5 w-3.5 text-brandred-600" />} onClick={async () => {
                      if (await confirm({ title: "Delete template?", danger: true, confirmText: "Delete", message: <>“{t.name}” will be deleted. Documents already generated are not affected.</> }))
                        run(() => api(`/api/templates/${t.id}`, { method: "DELETE" }), "Template deleted");
                    }} />}
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}
      <Modal open={!!preview} onClose={() => setPreview(null)} title={`Preview — ${preview?.name}`} width="max-w-[1100px]">
        {preview && <div className="h-[76vh]"><PdfViewer url={preview.url} /></div>}
      </Modal>
    </div>
  );
}

// ---------------------------------------------------------------- editor
function getP(o: any, path: string) { return path.split(".").reduce((a, k) => (a == null ? a : a[k]), o); }
function setP(o: any, path: string, v: any) {
  const c = structuredClone(o);
  const ks = path.split(".");
  let cur = c;
  for (const k of ks.slice(0, -1)) { cur[k] = cur[k] ?? {}; cur = cur[k]; }
  cur[ks[ks.length - 1]] = v;
  return c;
}

function TemplateEditor({ id }: { id: string }) {
  const toast = useToast();
  const [rec, setRec] = useState<Template | null>(null);
  const [cfg, setCfg] = useState<any>(null);
  const [families, setFamilies] = useState<string[]>([]);
  const [profiles, setProfiles] = useState<Branding[]>([]);
  const [prev, setPrev] = useState<{ url: string; issues: Issue[]; errors: string[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [section, setSection] = useState("general");
  const [picker, setPicker] = useState<string | null>(null);
  const n = useRef(0);

  useEffect(() => {
    (async () => {
      const [f, b] = await Promise.all([api("/api/fonts"), api<Branding[]>("/api/branding")]);
      setFamilies(f.families.map((x: { family: string }) => x.family));
      setProfiles(b);
      if (id === "new") {
        const d = await api("/api/templates/defaults");
        const def = b.find((x) => x.is_default);
        setCfg({ ...d.template, name: "New template", branding: def ? def.config : d.template.branding, branding_profile_id: null });
      } else {
        const t = await api<Template>(`/api/templates/${id}`);
        setRec(t); setCfg(t.config);
      }
    })().catch((e) => toast("error", errMsg(e)));
  }, [id, toast]);

  useEffect(() => {
    if (!cfg) return;
    const k = ++n.current;
    const t = setTimeout(async () => {
      setBusy(true);
      try {
        let c = cfg;
        if (cfg.branding_profile_id) { const p = profiles.find((x) => x.id === cfg.branding_profile_id); if (p) c = { ...cfg, branding: p.config }; }
        const r = await api("/api/templates/preview", { body: { config: c } });
        if (k === n.current) setPrev({ url: fileUrl(r.url), issues: r.issues, errors: r.errors });
      } catch (e) { if (k === n.current) toast("error", errMsg(e)); }
      finally { if (k === n.current) setBusy(false); }
    }, 700);
    return () => clearTimeout(t);
  }, [cfg, profiles, toast]);

  if (!cfg) return <div className="flex justify-center py-24"><Spinner /></div>;
  const ro = !!rec?.builtin;
  const v = (p: string) => getP(cfg, p);
  const s = (p: string) => (val: any) => setCfg((c: any) => setP(c, p, val));
  const save = async () => {
    setSaving(true);
    try {
      const out = id === "new" ? await api<Template>("/api/templates", { body: cfg }) : await api<Template>(`/api/templates/${id}`, { method: "PUT", body: cfg });
      toast("success", "Template saved");
      if (id === "new") navigate(`templates/${out.id}`); else { setRec(out); setCfg(out.config); }
    } catch (e) { toast("error", errMsg(e)); } finally { setSaving(false); }
  };
  const dup = async () => {
    try { const t = await api<Template>(`/api/templates/${id}/duplicate`, { body: { name: `${rec!.name} (my version)` } }); toast("success", "Copy created — you can edit it now."); navigate(`templates/${t.id}`); }
    catch (e) { toast("error", errMsg(e)); }
  };
  const SECTIONS = [["general", "General"], ["branding", "Branding"], ["page", "Page & margins"], ["fonts", "Fonts"], ["header", "Header & footer"], ["cover", "Cover page"],
    ["questions", "Questions"], ["sections", "Sections & instructions"], ["tables", "Tables"], ["images", "Images"], ["layouts", "Page layouts"], ["pagination", "Pagination"], ["export", "Export"]];
  const fam = families.map((f) => ({ value: f, label: f }));
  const asset = (path: string, label: string) => (
    <Field label={label}>
      <div className="flex items-center gap-2">
        <div className="h-12 w-20 rounded border border-slate-200 bg-slate-50 flex items-center justify-center overflow-hidden">
          {v(path) ? <img src={fileUrl(`/api/assets/${v(path)}/thumb?size=160`)} alt="" className="max-h-full max-w-full" /> : <ImageIcon className="h-5 w-5 text-slate-300" />}
        </div>
        <Button size="sm" disabled={ro} onClick={() => setPicker(path)}>Choose…</Button>
        {v(path) && <Button size="sm" variant="ghost" disabled={ro} onClick={() => s(path)(null)}>Remove</Button>}
      </div>
    </Field>
  );

  return (
    <div className="flex flex-col h-[calc(100vh-56px)]">
      <div className="flex items-center gap-3 mb-4">
        <Button variant="ghost" icon={<ArrowLeft className="h-4 w-4" />} onClick={() => navigate("templates")}>Templates</Button>
        <div className="text-xl font-bold text-navy-900 flex-1 truncate">{cfg.name}</div>
        {ro ? <><Badge><Lock className="h-3 w-3" />Built-in (read-only)</Badge><Button variant="primary" icon={<Copy className="h-4 w-4" />} onClick={dup}>Duplicate to edit</Button></>
          : <Button variant="primary" loading={saving} onClick={save}>Save template</Button>}
      </div>
      <div className="flex gap-5 flex-1 min-h-0">
        <div className="w-44 shrink-0 space-y-0.5">
          {SECTIONS.map(([k, l]) => <button key={k} onClick={() => setSection(k)} className={cx("w-full text-left px-3 py-2 rounded-lg text-sm", section === k ? "bg-royal-50 text-royal-700 font-semibold" : "text-slate-600 hover:bg-slate-100")}>{l}</button>)}
        </div>
        <Card className="w-[400px] shrink-0 p-5 overflow-auto">
          <fieldset disabled={ro} className="space-y-4">
            {section === "general" && <>
              <Field label="Template name"><TextInput value={v("name")} onChange={(e) => s("name")(e.target.value)} /></Field>
              <Field label="Examination type"><Select value={v("category")} onChange={s("category")} options={CATEGORIES.map(([a, b]) => ({ value: a, label: b }))} /></Field>
              <Field label="Description"><TextArea rows={3} value={v("description")} onChange={(e) => s("description")(e.target.value)} /></Field>
              <Field label="Tags (for recommendations)" hint="Comma separated, e.g. listening, a2, quiz"><TextInput value={(v("tags") || []).join(", ")} onChange={(e) => s("tags")(e.target.value.split(",").map((x: string) => x.trim()).filter(Boolean))} /></Field>
            </>}
            {section === "branding" && <>
              <Field label="Branding source" hint="Link a reusable branding profile, or design custom branding for this template only">
                <Select value={v("branding_profile_id") || ""} onChange={(x) => s("branding_profile_id")(x || null)} options={[{ value: "", label: "Custom branding (below)" }, ...profiles.map((p) => ({ value: p.id, label: `Profile: ${p.name}` }))]} />
              </Field>
              {v("branding_profile_id") ? <div className="text-sm text-slate-500">Logo, colours, watermark and texts come from the selected profile (edit them in Organization Branding).</div> : <BrandingFields cfg={cfg.branding} set={(p, val) => s(`branding.${p}`)(val)} asset={(p, l) => asset(`branding.${p}`, l)} />}
            </>}
            {section === "page" && <>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Paper"><Select value={v("page.size")} onChange={s("page.size")} options={[{ value: "A4", label: "A4" }, { value: "A5", label: "A5" }, { value: "custom", label: "Custom" }]} /></Field>
                <Field label="Orientation"><Select value={v("page.orientation")} onChange={s("page.orientation")} options={[{ value: "portrait", label: "Portrait" }, { value: "landscape", label: "Landscape" }]} /></Field>
              </div>
              {v("page.size") === "custom" && <div className="grid grid-cols-2 gap-3">
                <Field label="Width (mm)"><NumberInput value={v("page.width_mm")} min={70} max={1200} onChange={s("page.width_mm")} /></Field>
                <Field label="Height (mm)"><NumberInput value={v("page.height_mm")} min={70} max={1200} onChange={s("page.height_mm")} /></Field>
              </div>}
              <div className="grid grid-cols-4 gap-2">
                {["top", "bottom", "left", "right"].map((k) => <Field key={k} label={`${k[0].toUpperCase()}${k.slice(1)} (mm)`}><NumberInput value={v(`page.margins_mm.${k}`)} min={5} max={80} onChange={s(`page.margins_mm.${k}`)} /></Field>)}
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Columns"><Select value={String(v("page.columns"))} onChange={(x) => s("page.columns")(Number(x))} options={[{ value: "1", label: "One column" }, { value: "2", label: "Two columns" }, { value: "3", label: "Three columns" }]} /></Field>
                <Field label="Column gap (mm)"><NumberInput value={v("page.column_gap_mm")} min={2} max={30} onChange={s("page.column_gap_mm")} /></Field>
              </div>
              <Field label="Page background colour"><ColorInput value={v("page.background.color")} onChange={s("page.background.color")} /></Field>
              {asset("page.background.image_asset", "Background image")}
              {v("page.background.image_asset") && <Field label="Background image opacity"><Slider value={v("page.background.image_opacity")} min={0.02} max={1} onChange={s("page.background.image_opacity")} format={(x) => `${Math.round(x * 100)}%`} /></Field>}
              <Toggle label="White content panel" checked={!!v("page.content_panel")} onChange={s("page.content_panel")} hint="Draws a white rounded panel behind the content (useful with coloured backgrounds)" />
            </>}
            {section === "fonts" && <>
              <Field label="Body font"><Select value={v("fonts.body")} onChange={s("fonts.body")} options={fam} /></Field>
              <Field label="Heading font"><Select value={v("fonts.heading")} onChange={s("fonts.heading")} options={fam} /></Field>
              <div className="grid grid-cols-3 gap-2">
                <Field label="Body (pt)"><NumberInput value={v("fonts.body_size")} min={6} max={24} step={0.5} onChange={s("fonts.body_size")} /></Field>
                <Field label="Question (pt)"><NumberInput value={v("fonts.question_size")} min={6} max={24} step={0.5} onChange={s("fonts.question_size")} /></Field>
                <Field label="Options (pt)"><NumberInput value={v("fonts.option_size")} min={6} max={24} step={0.5} onChange={s("fonts.option_size")} /></Field>
              </div>
              <div className="grid grid-cols-3 gap-2">
                {[0, 1, 2].map((i) => <Field key={i} label={`Heading ${i + 1} (pt)`}><NumberInput value={v("fonts.heading_sizes")[i]} min={8} max={40} step={0.5} onChange={(x) => s("fonts.heading_sizes")(v("fonts.heading_sizes").map((y: number, k: number) => (k === i ? x : y)))} /></Field>)}
              </div>
              <Field label="Line spacing"><Slider value={v("fonts.line_spacing")} min={1} max={2} step={0.05} onChange={s("fonts.line_spacing")} format={(x) => x.toFixed(2)} /></Field>
            </>}
            {section === "header" && <>
              <Toggle label="Show header" checked={v("header.enabled")} onChange={s("header.enabled")} />
              <Field label="Header style"><Select value={v("header.style")} onChange={s("header.style")} options={[{ value: "band", label: "Coloured band" }, { value: "line", label: "Line with accent" }, { value: "minimal", label: "Minimal" }]} /></Field>
              <Toggle label="Logo in header" checked={v("header.show_logo")} onChange={s("header.show_logo")} />
              <Toggle label="Organization name" checked={v("header.show_org")} onChange={s("header.show_org")} />
              <Toggle label="Examination title" checked={v("header.show_title")} onChange={s("header.show_title")} />
              <Field label="Header height (mm)"><NumberInput value={v("header.height_mm")} min={6} max={40} onChange={s("header.height_mm")} /></Field>
              <Field label="Header text override"><TextInput value={v("header.text") || ""} onChange={(e) => s("header.text")(e.target.value)} placeholder="uses the examination title" /></Field>
              <div className="border-t border-slate-100 pt-3" />
              <Toggle label="Show footer" checked={v("footer.enabled")} onChange={s("footer.enabled")} />
              <Field label="Footer text"><TextInput value={v("footer.text") ?? ""} onChange={(e) => s("footer.text")(e.target.value || null)} placeholder="uses the branding footer text" /></Field>
              <Toggle label="Page numbers" checked={v("footer.show_page_numbers")} onChange={s("footer.show_page_numbers")} />
              <Field label="Page number format" hint="{page} and {total} are replaced"><TextInput value={v("footer.page_number_format")} onChange={(e) => s("footer.page_number_format")(e.target.value)} /></Field>
              <Toggle label="Count the cover page" checked={v("footer.number_cover")} onChange={s("footer.number_cover")} />
            </>}
            {section === "cover" && <>
              <Toggle label="Cover page" checked={v("cover.enabled")} onChange={s("cover.enabled")} />
              <Field label="Cover design"><Select value={v("cover.style")} onChange={s("cover.style")} options={[{ value: "band", label: "Colour band" }, { value: "classic", label: "Classic frame" }, { value: "minimal", label: "Minimal" }]} /></Field>
              <Field label="Title" hint="Empty = document title"><TextInput value={v("cover.title") || ""} onChange={(e) => s("cover.title")(e.target.value || null)} /></Field>
              <Field label="Subtitle"><TextInput value={v("cover.subtitle")} onChange={(e) => s("cover.subtitle")(e.target.value)} /></Field>
              <Toggle label="Logo on cover" checked={v("cover.show_logo")} onChange={s("cover.show_logo")} />
              <Toggle label="Show question count" checked={v("cover.show_stats")} onChange={s("cover.show_stats")} />
              <Field label="Candidate fields (one per line)"><TextArea rows={5} value={(v("cover.fields") || []).join("\n")} onChange={(e) => s("cover.fields")(e.target.value.split("\n").filter((x: string) => x.trim()))} /></Field>
              <Field label="Cover instructions"><TextArea rows={3} value={v("cover.instructions")} onChange={(e) => s("cover.instructions")(e.target.value)} /></Field>
            </>}
            {section === "questions" && <>
              <Field label="Numbering" hint="Preserve keeps the original numbers; automatic renumbers 1, 2, 3… in the output (stored content is never changed)">
                <Select value={v("questions.numbering")} onChange={s("questions.numbering")} options={[{ value: "preserve", label: "Preserve original numbers" }, { value: "auto", label: "Automatic sequential numbering" }]} />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Number format" hint="{n} = number"><TextInput value={v("questions.number_format")} onChange={(e) => s("questions.number_format")(e.target.value)} /></Field>
                <Field label="Option label format" hint="{L} = letter"><TextInput value={v("questions.option_label_format")} onChange={(e) => s("questions.option_label_format")(e.target.value)} /></Field>
              </div>
              <Field label="Option letters"><Select value={v("questions.option_label_case")} onChange={s("questions.option_label_case")} options={[{ value: "preserve", label: "As in the original" }, { value: "upper", label: "A, B, C" }, { value: "lower", label: "a, b, c" }]} /></Field>
              <Field label="Option layout"><Select value={v("questions.option_layout")} onChange={s("questions.option_layout")} options={[{ value: "auto", label: "Automatic (fit to width)" }, { value: "vertical", label: "Vertical list" }, { value: "two_column", label: "Two columns" }, { value: "grid4", label: "Four columns" }]} /></Field>
              <Toggle label="Bold question numbers" checked={v("questions.bold_number")} onChange={s("questions.bold_number")} />
              <Field label="Number colour"><ColorInput value={v("questions.number_color")} onChange={s("questions.number_color")} /></Field>
              <Toggle label="Keep each question with its options" checked={v("questions.keep_together")} onChange={s("questions.keep_together")} />
              <Toggle label="Boxed questions" checked={v("questions.box")} onChange={s("questions.box")} />
              {v("questions.box") && <Field label="Box colour"><ColorInput value={v("questions.box_color")} onChange={s("questions.box_color")} /></Field>}
              <Toggle label="Show points" checked={v("questions.show_points")} onChange={s("questions.show_points")} />
              <div className="grid grid-cols-2 gap-3">
                <Field label="Space between (mm)"><NumberInput value={v("questions.space_between_mm")} min={0} max={20} step={0.5} onChange={s("questions.space_between_mm")} /></Field>
                <Field label="Answer lines (open)"><NumberInput value={v("questions.answer_lines")} min={0} max={20} onChange={s("questions.answer_lines")} /></Field>
              </div>
            </>}
            {section === "sections" && <>
              <Field label="Section heading style"><Select value={v("sections.style")} onChange={s("sections.style")} options={[{ value: "bar", label: "Coloured bar" }, { value: "underline", label: "Underlined" }, { value: "plain", label: "Plain" }]} /></Field>
              <Toggle label="Uppercase section titles (display only)" checked={v("sections.uppercase")} onChange={s("sections.uppercase")} />
              <Toggle label="Each section on a new page" checked={v("sections.page_break_before")} onChange={s("sections.page_break_before")} />
              <Field label="Section colour"><ColorInput value={v("sections.color")} onChange={s("sections.color")} /></Field>
              <Field label="Instruction style"><Select value={v("instructions.style")} onChange={s("instructions.style")} options={[{ value: "box", label: "Tinted box" }, { value: "plain", label: "Plain text" }]} /></Field>
              <Toggle label="Italic instructions" checked={v("instructions.italic")} onChange={s("instructions.italic")} />
            </>}
            {section === "tables" && <>
              <Field label="Header background"><ColorInput value={v("tables.header_bg")} onChange={s("tables.header_bg")} /></Field>
              <Field label="Header text colour"><ColorInput value={v("tables.header_color")} onChange={s("tables.header_color")} /></Field>
              <Field label="Border colour"><ColorInput value={v("tables.border_color")} onChange={s("tables.border_color")} /></Field>
              <Toggle label="Striped rows" checked={v("tables.stripe")} onChange={s("tables.stripe")} />
              <Toggle label="Repeat header row on each page" checked={v("tables.repeat_header")} onChange={s("tables.repeat_header")} />
              <div className="grid grid-cols-2 gap-3">
                <Field label="Font size (pt)"><NumberInput value={v("tables.font_size")} min={6} max={16} step={0.5} onChange={s("tables.font_size")} /></Field>
                <Field label="Minimum size (pt)" hint="Wide tables shrink to this size before anything else"><NumberInput value={v("tables.min_font_size")} min={5} max={12} step={0.5} onChange={s("tables.min_font_size")} /></Field>
              </div>
            </>}
            {section === "images" && <>
              <Field label="Maximum width"><Slider value={v("images.max_width_pct")} min={20} max={100} step={1} onChange={s("images.max_width_pct")} format={(x) => `${x}%`} /></Field>
              <Field label="Maximum height (of page)"><Slider value={v("images.max_height_pct")} min={20} max={95} step={1} onChange={s("images.max_height_pct")} format={(x) => `${x}%`} /></Field>
              <Field label="Alignment"><Select value={v("images.align")} onChange={s("images.align")} options={[{ value: "center", label: "Centered" }, { value: "left", label: "Left" }, { value: "right", label: "Right" }]} /></Field>
              <Toggle label="Maps and diagrams full width" checked={v("images.full_width_maps")} onChange={s("images.full_width_maps")} />
            </>}
            {section === "layouts" && <>
              <div className="text-sm text-slate-500">Sections can switch page layout (listening, reading, writing…). Each layout can have its own column count and header badge.</div>
              {Object.keys(v("layouts")).map((k) => (
                <div key={k} className="rounded-lg border border-slate-200 p-3">
                  <div className="font-medium text-sm text-navy-900 capitalize mb-2">{k.replace("_", " ")}</div>
                  <div className="grid grid-cols-2 gap-2">
                    <Field label="Columns"><Select value={String(v(`layouts.${k}.columns`) ?? "")} onChange={(x) => s(`layouts.${k}.columns`)(x ? Number(x) : null)} options={[{ value: "", label: "Page default" }, { value: "1", label: "1" }, { value: "2", label: "2" }]} /></Field>
                    <Field label="Header badge"><TextInput value={v(`layouts.${k}.badge`) || ""} onChange={(e) => s(`layouts.${k}.badge`)(e.target.value || null)} /></Field>
                  </div>
                </div>
              ))}
              <Toggle label="Answer sheet page at the end" checked={v("answer_sheet.enabled")} onChange={s("answer_sheet.enabled")} />
            </>}
            {section === "pagination" && <>
              <Field label="Layout density" hint="Readability is never sacrificed to reduce page count"><Select value={v("pagination.density")} onChange={s("pagination.density")} options={[{ value: "compact", label: "Compact" }, { value: "standard", label: "Standard" }, { value: "spacious", label: "Spacious" }]} /></Field>
              <Toggle label="Keep answer options with their question" checked={v("pagination.keep_options_with_question")} onChange={s("pagination.keep_options_with_question")} />
              <Toggle label="Prevent headings alone at page bottom" checked={v("pagination.avoid_orphan_headings")} onChange={s("pagination.avoid_orphan_headings")} />
              <Toggle label="Widow / orphan line control" checked={v("pagination.widow_orphan_control")} onChange={s("pagination.widow_orphan_control")} />
              <Toggle label="New page when the section layout changes" checked={v("pagination.section_layout_page_breaks")} onChange={s("pagination.section_layout_page_breaks")} />
              <Toggle label="Keep the original document's page breaks" checked={v("pagination.preserve_source_page_breaks")} onChange={s("pagination.preserve_source_page_breaks")} />
            </>}
            {section === "export" && <>
              <Field label="Main PDF quality"><Select value={v("export.quality")} onChange={s("export.quality")} options={[{ value: "print", label: "High-quality print (300 dpi images)" }, { value: "standard", label: "Standard (200 dpi)" }, { value: "compressed", label: "Compressed (120 dpi)" }]} /></Field>
              <Toggle label="Grayscale output" checked={v("export.grayscale")} onChange={s("export.grayscale")} />
              <Toggle label="Also create a compressed copy" checked={v("export.compressed_copy")} onChange={s("export.compressed_copy")} />
              <Toggle label="Save page images (PNG) with each export" checked={!!v("export.page_images")} onChange={s("export.page_images")} />
            </>}
          </fieldset>
        </Card>
        <div className="flex-1 min-w-0 flex flex-col gap-3">
          <div className="flex items-center gap-2 text-xs text-slate-500">{busy ? <><Spinner className="h-3.5 w-3.5" />Updating live preview…</> : "Live preview with a sample examination (same engine as the final PDF)"}</div>
          {prev?.errors?.length ? <div className="rounded-lg bg-brandred-50 text-brandred-700 text-sm px-4 py-2">{prev.errors.join(" ")}</div> : null}
          <div className="flex-1 min-h-0">{prev ? <PdfViewer url={prev.url} showThumbs={false} /> : <div className="flex justify-center py-20"><Spinner /></div>}</div>
          {!!prev?.issues?.length && <div className="max-h-28 overflow-auto"><IssueList issues={prev.issues} /></div>}
        </div>
      </div>
      <AssetPicker open={!!picker} onClose={() => setPicker(null)} kinds="logo,image,watermark,background" onPick={(a) => { if (picker) s(picker)(a.id); setPicker(null); }} />
    </div>
  );
}

export function BrandingFields({ cfg, set, asset }: { cfg: any; set: (path: string, v: any) => void; asset: (path: string, label: string) => React.ReactNode }) {
  const g = (p: string) => getP(cfg, p);
  return (
    <div className="space-y-4">
      <Field label="Organization name"><TextInput value={g("org_name")} onChange={(e) => set("org_name", e.target.value)} /></Field>
      <div className="grid grid-cols-2 gap-3">{asset("logo_asset", "Primary logo")}{asset("secondary_logo_asset", "Secondary logo")}</div>
      <div className="grid grid-cols-2 gap-3">
        {(["primary", "secondary", "accent", "text"] as const).map((k) => <Field key={k} label={`${k[0].toUpperCase()}${k.slice(1)} colour`}><ColorInput value={g(`colors.${k}`)} onChange={(v) => set(`colors.${k}`, v)} /></Field>)}
      </div>
      <Field label="Examination title"><TextInput value={g("exam_title")} onChange={(e) => set("exam_title", e.target.value)} placeholder="empty = document title" /></Field>
      <Field label="Teacher name"><TextInput value={g("teacher_name")} onChange={(e) => set("teacher_name", e.target.value)} /></Field>
      <Field label="Header text"><TextInput value={g("header_text")} onChange={(e) => set("header_text", e.target.value)} /></Field>
      <Field label="Footer text"><TextInput value={g("footer_text")} onChange={(e) => set("footer_text", e.target.value)} /></Field>
      <Field label="Contact information"><TextInput value={g("contact")} onChange={(e) => set("contact", e.target.value)} /></Field>
      <div className="rounded-lg border border-slate-200 p-3 space-y-3">
        <div className="text-sm font-medium text-navy-900">Watermark</div>
        <Select value={g("watermark.type") || "none"} onChange={(v) => set("watermark.type", v)} options={[{ value: "none", label: "No watermark" }, { value: "text", label: "Text" }, { value: "image", label: "Image" }]} />
        {g("watermark.type") === "text" && <Field label="Watermark text"><TextInput value={g("watermark.text")} onChange={(e) => set("watermark.text", e.target.value)} /></Field>}
        {g("watermark.type") === "image" && asset("watermark.asset", "Watermark image")}
        {g("watermark.type") !== "none" && <>
          <Field label="Opacity"><Slider value={g("watermark.opacity") ?? 0.06} min={0.02} max={0.4} step={0.01} onChange={(v) => set("watermark.opacity", v)} format={(v) => `${Math.round(v * 100)}%`} /></Field>
          <Field label="Angle"><Slider value={g("watermark.angle") ?? 45} min={-90} max={90} step={1} onChange={(v) => set("watermark.angle", v)} format={(v) => `${v}°`} /></Field>
          <Field label="Layer"><Select value={g("watermark.layer") || "under"} onChange={(v) => set("watermark.layer", v)} options={[{ value: "under", label: "Behind content" }, { value: "over", label: "Over content" }]} /></Field>
        </>}
      </div>
    </div>
  );
}
