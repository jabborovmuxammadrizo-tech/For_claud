import { FileCheck2, FileText, FolderOpen, HardDrive, LayoutTemplate, Upload, Zap } from "lucide-react";
import { useEffect, useState } from "react";
import { navigate, Route } from "../App";
import { api, Doc, ExportRec, saveFile } from "../api";
import { Badge, Button, Card, EmptyState, fmtBytes, fmtDate, Progress, SectionTitle, Spinner, useToast } from "../components/ui";

type Dash = {
  counts: Record<string, number>; recent_documents: Doc[]; recent_exports: ExportRec[];
  history: { id: string; kind: string; status: string; progress: number; created: number; finished: number; error: string; title: string }[];
  storage: { by_folder: Record<string, number>; total: number; free: number | null; root: string };
};

export function StatusBadge({ status }: { status: string }) {
  const map: Record<string, [string, "green" | "amber" | "red" | "blue" | "slate"]> = {
    succeeded: ["Done", "green"], generated: ["Generated", "green"], needs_review: ["Review", "amber"], failed: ["Failed", "red"],
    running: ["Running", "blue"], queued: ["Queued", "blue"], imported: ["Imported", "slate"], edited: ["Edited", "blue"], uploaded: ["Uploaded", "slate"],
  };
  const [label, tone] = map[status] || [status, "slate"];
  return <Badge tone={tone}>{label}</Badge>;
}

export default function Dashboard(_: { route: Route }) {
  const [d, setD] = useState<Dash | null>(null);
  const toast = useToast();
  useEffect(() => { api<Dash>("/api/dashboard").then(setD).catch((e) => toast("error", String(e))); }, [toast]);
  if (!d) return <div className="flex justify-center py-24"><Spinner /></div>;
  const stats = [
    { label: "Documents", value: d.counts.documents, icon: FileText, tone: "text-royal-600 bg-royal-50" },
    { label: "PDFs generated", value: d.counts.generated, icon: FileCheck2, tone: "text-emerald-600 bg-emerald-50" },
    { label: "Saved templates", value: d.counts.templates, icon: LayoutTemplate, tone: "text-violet-600 bg-violet-50" },
    { label: "Exports", value: d.counts.exports, icon: HardDrive, tone: "text-amber-600 bg-amber-50" },
  ];
  const maxFolder = Math.max(1, ...Object.values(d.storage.by_folder));
  return (
    <div>
      <SectionTitle title="Dashboard" subtitle="Welcome back. Turn any examination into a branded, print-ready PDF in seconds." />
      <Card className="p-7 mb-6 bg-gradient-to-br from-navy-900 via-navy-800 to-royal-700 text-white border-0 relative overflow-hidden">
        <div className="absolute -right-10 -top-16 h-64 w-64 rounded-full bg-white/5" />
        <div className="absolute right-24 -bottom-24 h-56 w-56 rounded-full bg-brandred-600/20" />
        <div className="relative flex items-center justify-between gap-6">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[.18em] text-white/60">Quick Generator</div>
            <div className="text-2xl font-bold mt-2">Upload · Choose template · Generate</div>
            <div className="text-white/70 text-sm mt-1.5 max-w-xl">Questions, answer options, tables and images are preserved exactly. Layout, numbering, branding and quality checks are automatic.</div>
          </div>
          <Button size="lg" className="bg-white text-navy-900 hover:bg-royal-50 shadow-lift" icon={<Zap className="h-5 w-5 text-brandred-600" />} onClick={() => navigate("quick")}>Quick generate</Button>
        </div>
      </Card>
      <div className="grid grid-cols-4 gap-4 mb-6">
        {stats.map((s) => (
          <Card key={s.label} className="p-5 flex items-center gap-4">
            <div className={`h-11 w-11 rounded-xl flex items-center justify-center ${s.tone}`}><s.icon className="h-5 w-5" /></div>
            <div><div className="text-2xl font-bold text-navy-900 tabular-nums">{s.value}</div><div className="text-xs text-slate-500">{s.label}</div></div>
          </Card>
        ))}
      </div>
      <div className="grid grid-cols-3 gap-6">
        <Card className="col-span-2 p-5">
          <div className="flex items-center justify-between mb-3">
            <div className="font-semibold text-navy-900">Recent documents</div>
            <Button size="sm" variant="ghost" icon={<FolderOpen className="h-4 w-4" />} onClick={() => navigate("documents")}>All documents</Button>
          </div>
          {!d.recent_documents.length ? (
            <EmptyState icon={<Upload className="h-6 w-6" />} title="No documents yet" text="Upload your first examination to get started."
              action={<Button variant="primary" onClick={() => navigate("quick")}>Upload a document</Button>} />
          ) : (
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-slate-500 border-b border-slate-100"><th className="py-2 font-medium">Title</th><th className="font-medium">Questions</th><th className="font-medium">Status</th><th className="font-medium">Updated</th></tr></thead>
              <tbody>
                {d.recent_documents.map((doc) => (
                  <tr key={doc.id} className="border-b border-slate-50 hover:bg-slate-50 cursor-pointer" onClick={() => navigate(`editor/${doc.id}`)}>
                    <td className="py-2.5 font-medium text-navy-900 truncate max-w-[280px]">{doc.title}<div className="text-[11px] text-slate-400 font-normal">{doc.source_name}</div></td>
                    <td className="tabular-nums">{doc.question_count ?? "—"}</td>
                    <td><StatusBadge status={doc.status} /></td>
                    <td className="text-slate-500 text-xs">{fmtDate(doc.updated)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card className="p-5">
          <div className="font-semibold text-navy-900 mb-3">Storage</div>
          <div className="text-2xl font-bold text-navy-900">{fmtBytes(d.storage.total)}</div>
          <div className="text-xs text-slate-500 mb-4">used · {d.storage.free != null ? `${fmtBytes(d.storage.free)} free on disk` : ""}</div>
          <div className="space-y-2.5">
            {Object.entries(d.storage.by_folder).map(([k, v]) => (
              <div key={k}><div className="flex justify-between text-xs mb-1"><span className="text-slate-600">{k}</span><span className="tabular-nums text-slate-500">{fmtBytes(v)}</span></div><Progress value={v / maxFolder} className="h-1.5" /></div>
            ))}
          </div>
          <div className="text-[11px] text-slate-400 mt-4 break-all">{d.storage.root}</div>
        </Card>
        <Card className="col-span-2 p-5">
          <div className="font-semibold text-navy-900 mb-3">Processing history</div>
          {!d.history.length ? <div className="text-sm text-slate-500">No processing yet.</div> : (
            <div className="divide-y divide-slate-50">
              {d.history.map((h) => (
                <div key={h.id} className="flex items-center gap-3 py-2 text-sm">
                  <StatusBadge status={h.status} />
                  <div className="flex-1 truncate text-navy-900">{h.title || "—"} <span className="text-slate-400 text-xs">· {h.kind === "generate" ? "generation" : "import"}</span></div>
                  {h.error && <div className="text-xs text-brandred-600 truncate max-w-[260px]" title={h.error}>{h.error}</div>}
                  <div className="text-xs text-slate-400 w-36 text-right">{fmtDate(h.created)}</div>
                </div>
              ))}
            </div>
          )}
        </Card>
        <Card className="p-5">
          <div className="font-semibold text-navy-900 mb-3">Recent exports</div>
          {!d.recent_exports.length ? <div className="text-sm text-slate-500">No exports yet.</div> : (
            <div className="space-y-2">
              {d.recent_exports.map((e) => (
                <button key={e.id} onClick={() => saveFile(`/api/exports/${e.id}/file`, e.path.split(/[\\/]/).pop() || "export.pdf").catch((x) => toast("error", String(x)))}
                  className="w-full text-left flex items-center gap-3 rounded-lg px-2 py-1.5 hover:bg-slate-50">
                  <FileCheck2 className="h-4 w-4 text-emerald-600 shrink-0" />
                  <div className="flex-1 min-w-0"><div className="text-sm text-navy-900 truncate">{e.path.split(/[\\/]/).pop()}</div><div className="text-[11px] text-slate-400">{e.kind} · {fmtBytes(e.size)}</div></div>
                </button>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
