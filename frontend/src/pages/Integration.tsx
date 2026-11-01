import { FolderOpen, MonitorCog, RotateCcw, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, Template } from "../api";
import { Badge, Button, Card, errMsg, Field, Select, Spinner, TextInput, Toggle, useDialogs, useToast } from "../components/ui";

type St = Record<string, any>;
const TOGGLES: [string, string, string][] = [
  ["shell_menu_pdf", "PDF right-click menu", "PDF Test Designer submenu on .pdf files"],
  ["shell_menu_docx", "DOCX right-click menu", "Submenu on Word documents"],
  ["shell_menu_folder", "Folder right-click menu", "Generate all supported documents in a folder"],
  ["shell_menu_image", "Image right-click menu", "PNG, JPG, BMP, TIFF: image library, watermark, background, PDF"],
  ["shell_batch", "Batch generation entries", "Batch generate / Open all for multiple selected files"],
  ["shell_default_action", "Default template action", "“Generate PDF Using Default Template”"],
  ["shell_background", "Background processing", "Process in a small task window without opening the main application"],
  ["shell_notifications", "Completion notifications", "Windows notification when a right-click task finishes"],
];

export default function Integration() {
  const toast = useToast();
  const { confirm } = useDialogs();
  const [st, setSt] = useState<St | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [status, setStatus] = useState<any>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const load = useCallback(async () => {
    const [s, t] = await Promise.all([api<St>("/api/settings"), api<Template[]>("/api/templates")]);
    setSt(s); setTemplates(t);
    if (window.ptd) setStatus(await window.ptd.integration.status());
  }, []);
  useEffect(() => { load().catch((e) => toast("error", errMsg(e))); }, [load, toast]);

  const save = async (patch: St) => {
    try {
      const next = await api<St>("/api/settings", { method: "PUT", body: patch });
      setSt(next);
      const menuKey = Object.keys(patch).some((k) => k.startsWith("shell_menu") || k === "shell_batch" || k === "shell_default_action");
      if (menuKey && window.ptd && status?.platform === "win32") {
        const r = await window.ptd.integration.apply(next) as { ok: boolean; error?: string };
        if (!r.ok) toast("error", r.error || "Could not update the Explorer menu");
        else toast("success", "File Explorer menu updated.");
        setStatus(await window.ptd.integration.status());
      }
    } catch (e) { toast("error", errMsg(e)); }
  };
  const act = async (key: string, fn: () => Promise<any>, ok: string) => {
    setBusy(key);
    try { const r = await fn(); if (r && r.ok === false) toast("error", r.error); else toast("success", ok); if (window.ptd) setStatus(await window.ptd.integration.status()); }
    catch (e) { toast("error", errMsg(e)); } finally { setBusy(null); }
  };
  if (!st) return <Spinner />;
  const win = status?.platform === "win32";
  const naming = st.output_naming;
  const example = (naming === "custom" ? st.output_pattern : naming === "exam" ? "{name}_Exam" : "{name}_Formatted")
    .replace("{name}", "Oʻquvchilar testi").replace("{template}", "Standard").replace("{date}", new Date().toISOString().slice(0, 10)).replace("{time}", "0930") + ".pdf";
  return (
    <div className="grid grid-cols-2 gap-6">
      <Card className="p-6 col-span-2">
        <div className="flex items-start gap-4">
          <div className="h-11 w-11 rounded-xl bg-royal-50 text-royal-600 flex items-center justify-center"><MonitorCog className="h-6 w-6" /></div>
          <div className="flex-1">
            <div className="font-semibold text-navy-900">Windows File Explorer integration</div>
            <div className="text-sm text-slate-500 mt-1">Right-click a PDF, Word document, folder or image → <b>PDF Test Designer</b> → choose an action. On Windows 11 the menu is under <b>Show more options</b> (or Shift + right-click).</div>
            <div className="flex flex-wrap gap-2 mt-3 items-center">
              {!window.ptd ? <Badge>Available in the desktop application</Badge> : !win ? <Badge tone="amber">Windows only — not available on {status?.platform}</Badge> : <>
                <Badge tone={status.machine ? "green" : "slate"}><ShieldCheck className="h-3 w-3" />{status.machine ? "Registered for all users (installer)" : "Not registered by the installer"}</Badge>
                <Badge tone={status.user ? "blue" : "slate"}>{status.user ? "Per-user settings active" : "No per-user overrides"}</Badge>
              </>}
            </div>
          </div>
          {win && (
            <div className="flex flex-col gap-2">
              <Button size="sm" icon={<RotateCcw className="h-4 w-4" />} loading={busy === "restore"} onClick={async () => {
                if (await confirm({ title: "Restore default integration?", message: "All right-click menus are re-enabled with the standard entries. Your output folder and naming settings are kept.", confirmText: "Restore" })) {
                  await save({ shell_menu_pdf: true, shell_menu_docx: true, shell_menu_folder: true, shell_menu_image: true, shell_batch: true, shell_default_action: true });
                  act("restore", () => window.ptd!.integration.restore(), "Default Explorer integration restored.");
                }
              }}>Restore default integration</Button>
              {!status?.machine && <Button size="sm" loading={busy === "reg"} onClick={() => act("reg", () => window.ptd!.integration.registerUser(), "Context menu registered for your Windows account.")}>Register for my account (portable)</Button>}
              {status?.user && !status?.machine && <Button size="sm" variant="ghost" loading={busy === "unreg"} onClick={() => act("unreg", () => window.ptd!.integration.unregisterUser(), "Context menu removed for your account.")}>Remove for my account</Button>}
            </div>
          )}
        </div>
      </Card>
      <Card className="p-6">
        <div className="font-semibold text-navy-900 mb-2">Menus and behaviour</div>
        {TOGGLES.map(([k, l, h]) => <Toggle key={k} label={l} hint={h} checked={st[k] !== false} onChange={(v) => save({ [k]: v })} />)}
        <Toggle label="Include subfolders when a folder is selected" checked={!!st.shell_include_subfolders} onChange={(v) => save({ shell_include_subfolders: v })} />
        <Toggle label="Also create a ZIP of batch results" checked={!!st.output_zip} onChange={(v) => save({ output_zip: v })} />
        <Field label="Template for right-click generation" className="mt-3">
          <Select value={st.shell_default_template || ""} onChange={(v) => save({ shell_default_template: v })}
            options={[{ value: "", label: "Application default template" }, ...templates.map((t) => ({ value: t.id, label: t.name }))]} />
        </Field>
      </Card>
      <Card className="p-6 space-y-4">
        <div className="font-semibold text-navy-900">Output folder and file names</div>
        <Field label="Output folder" hint="Generated files are saved here. Originals are never modified or overwritten.">
          <div className="flex gap-2">
            <TextInput value={st.output_dir || ""} placeholder={st.output_dir_effective} onChange={(e) => setSt({ ...st, output_dir: e.target.value })} onBlur={() => save({ output_dir: st.output_dir })} />
            {window.ptd && <Button icon={<FolderOpen className="h-4 w-4" />} onClick={async () => { const d = await window.ptd!.chooseFolder(); if (d) save({ output_dir: d }); }}>Browse</Button>}
          </div>
          {st.output_dir && <button className="text-xs text-royal-700 hover:underline mt-1" onClick={() => save({ output_dir: "" })}>Use the default folder ({st.output_dir_effective})</button>}
        </Field>
        <Field label="File naming">
          <Select value={naming} onChange={(v) => save({ output_naming: v })} options={[{ value: "formatted", label: "OriginalName_Formatted.pdf" }, { value: "exam", label: "OriginalName_Exam.pdf" }, { value: "custom", label: "Custom pattern" }]} />
        </Field>
        {naming === "custom" && (
          <Field label="Custom pattern" hint="{name} original file name · {template} template name · {date} · {time}">
            <TextInput value={st.output_pattern} onChange={(e) => setSt({ ...st, output_pattern: e.target.value })} onBlur={() => save({ output_naming: "custom", output_pattern: st.output_pattern })} />
          </Field>
        )}
        <div className="text-xs text-slate-500">Example: <span className="font-mono text-navy-900">{example}</span>. If the name exists, “ (2)”, “ (3)”… is added — files are never overwritten.</div>
      </Card>
    </div>
  );
}
