import { Copy, Folder, FolderPlus, MoreHorizontal, PenTool, RotateCcw, Search, Trash2, Upload, Zap } from "lucide-react";
import React, { useCallback, useEffect, useState } from "react";
import { navigate, Route } from "../App";
import { api, Doc } from "../api";
import { Button, Card, cx, EmptyState, errMsg, fmtDate, Select, SectionTitle, TextInput, useDialogs, useToast } from "../components/ui";
import { StatusBadge } from "./Dashboard";

type FolderRec = { id: string; name: string; count: number };

export default function Documents(_: { route: Route }) {
  const toast = useToast();
  const { confirm, prompt } = useDialogs();
  const [docs, setDocs] = useState<Doc[]>([]);
  const [folders, setFolders] = useState<FolderRec[]>([]);
  const [folder, setFolder] = useState<string>("all");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("updated");
  const [menu, setMenu] = useState<string | null>(null);

  const load = useCallback(async () => {
    const params = new URLSearchParams({ sort });
    if (q) params.set("q", q);
    if (folder === "trash") params.set("trash", "true");
    else if (folder !== "all") params.set("folder_id", folder);
    const [d, f] = await Promise.all([api<Doc[]>(`/api/documents?${params}`), api<FolderRec[]>("/api/folders")]);
    setDocs(d); setFolders(f);
  }, [q, sort, folder]);
  useEffect(() => { const t = setTimeout(() => load().catch((e) => toast("error", errMsg(e))), 200); return () => clearTimeout(t); }, [load, toast]);

  const run = async (fn: () => Promise<unknown>, ok?: string) => {
    try { await fn(); if (ok) toast("success", ok); await load(); } catch (e) { toast("error", errMsg(e)); }
  };
  const newFolder = async () => { const n = await prompt({ title: "New folder", label: "Folder name", confirmText: "Create" }); if (n) run(() => api("/api/folders", { body: { name: n } })); };
  const rename = async (d: Doc) => { const n = await prompt({ title: "Rename document", label: "Title", initial: d.title, confirmText: "Rename" }); if (n) run(() => api(`/api/documents/${d.id}`, { method: "PATCH", body: { title: n } })); };
  const trash = async (d: Doc) => {
    if (await confirm({ title: "Move to trash?", message: <>“{d.title}” will be moved to the trash. You can restore it later.</>, confirmText: "Move to trash", danger: true }))
      run(() => api(`/api/documents/${d.id}`, { method: "DELETE" }), "Moved to trash");
  };
  const destroy = async (d: Doc) => {
    if (await confirm({ title: "Delete permanently?", danger: true, confirmText: "Delete forever", requireText: "DELETE",
      message: <>This permanently deletes “{d.title}”, its original file, edits and version history. Generated PDFs in the Exports folder are kept. This cannot be undone.</> }))
      run(() => api(`/api/documents/${d.id}?permanent=true`, { method: "DELETE" }), "Deleted");
  };
  const deleteFolder = async (f: FolderRec) => {
    if (await confirm({ title: "Delete folder?", message: <>The folder “{f.name}” will be removed. Its {f.count} document(s) are kept and moved to “All documents”.</>, confirmText: "Delete folder", danger: true }))
      run(() => api(`/api/folders/${f.id}`, { method: "DELETE" }).then(() => setFolder("all")));
  };

  return (
    <div onClick={() => setMenu(null)}>
      <SectionTitle title="My Documents" subtitle="All imported examinations, their edits and generated PDFs."
        actions={<><Button icon={<FolderPlus className="h-4 w-4" />} onClick={newFolder}>New folder</Button><Button variant="primary" icon={<Upload className="h-4 w-4" />} onClick={() => navigate("import")}>Import document</Button></>} />
      <div className="flex gap-6">
        <div className="w-56 shrink-0 space-y-0.5">
          {[{ id: "all", name: "All documents" }, ...folders, { id: "trash", name: "Trash" }].map((f) => (
            <div key={f.id} className={cx("group flex items-center gap-2 rounded-lg px-3 py-2 text-sm cursor-pointer", folder === f.id ? "bg-royal-50 text-royal-700 font-semibold" : "text-slate-600 hover:bg-slate-100")}
              onClick={() => setFolder(f.id)}>
              {f.id === "trash" ? <Trash2 className="h-4 w-4" /> : <Folder className="h-4 w-4" />}
              <span className="flex-1 truncate">{f.name}</span>
              {"count" in f && <span className="text-xs text-slate-400">{(f as FolderRec).count}</span>}
              {"count" in f && <button className="hidden group-hover:block text-slate-400 hover:text-brandred-600" title="Delete folder" onClick={(e) => { e.stopPropagation(); deleteFolder(f as FolderRec); }}><Trash2 className="h-3.5 w-3.5" /></button>}
            </div>
          ))}
        </div>
        <Card className="flex-1 p-0 overflow-visible">
          <div className="flex items-center gap-3 p-4 border-b border-slate-100">
            <div className="relative flex-1"><Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" /><TextInput className="pl-9" placeholder="Search by title or file name…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
            <Select className="w-48" value={sort} onChange={setSort} options={[{ value: "updated", label: "Recently updated" }, { value: "created", label: "Recently created" }, { value: "title", label: "Title A–Z" }, { value: "questions", label: "Most questions" }]} />
          </div>
          {!docs.length ? (
            <EmptyState icon={folder === "trash" ? <Trash2 className="h-6 w-6" /> : <Upload className="h-6 w-6" />} title={folder === "trash" ? "Trash is empty" : q ? "No matching documents" : "No documents here yet"}
              text={folder === "trash" ? "Deleted documents appear here and can be restored." : "Import a PDF or DOCX examination to start."}
              action={folder !== "trash" && <Button variant="primary" onClick={() => navigate("quick")}>Upload a document</Button>} />
          ) : (
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-slate-500 border-b border-slate-100"><th className="py-2.5 px-4 font-medium">Title</th><th className="font-medium">Type</th><th className="font-medium">Questions</th><th className="font-medium">Pages</th><th className="font-medium">Status</th><th className="font-medium">Updated</th><th /></tr></thead>
              <tbody>
                {docs.map((d) => (
                  <tr key={d.id} className="border-b border-slate-50 hover:bg-slate-50/70">
                    <td className="py-2.5 px-4 max-w-[320px]">
                      <button className="font-medium text-navy-900 hover:text-royal-700 text-left truncate block max-w-full" onClick={() => folder !== "trash" && navigate(`editor/${d.id}`)}>{d.title}</button>
                      <div className="text-[11px] text-slate-400 truncate">{d.source_name}{d.import_mode === "original" ? " · original pages" : ""}</div>
                    </td>
                    <td className="uppercase text-xs text-slate-500">{d.kind}</td>
                    <td className="tabular-nums">{d.question_count ?? "—"}</td>
                    <td className="tabular-nums">{d.page_count ?? "—"}</td>
                    <td><StatusBadge status={d.status} /></td>
                    <td className="text-xs text-slate-500">{fmtDate(d.updated)}</td>
                    <td className="pr-3 text-right relative">
                      {folder === "trash" ? (
                        <div className="flex gap-1 justify-end">
                          <Button size="sm" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={() => run(() => api(`/api/documents/${d.id}/restore`, { method: "POST" }), "Restored")}>Restore</Button>
                          <Button size="sm" variant="danger" onClick={() => destroy(d)}>Delete</Button>
                        </div>
                      ) : (
                        <div className="flex gap-1 justify-end">
                          <Button size="sm" variant="ghost" icon={<PenTool className="h-3.5 w-3.5" />} onClick={() => navigate(`editor/${d.id}`)}>Edit</Button>
                          <Button size="sm" variant="ghost" icon={<Zap className="h-3.5 w-3.5" />} onClick={() => navigate(`editor/${d.id}?generate=1`)}>Generate</Button>
                          <button className="p-1.5 rounded hover:bg-slate-200 text-slate-500" onClick={(e) => { e.stopPropagation(); setMenu(menu === d.id ? null : d.id); }} aria-label="More actions"><MoreHorizontal className="h-4 w-4" /></button>
                          {menu === d.id && (
                            <div className="absolute right-3 top-10 z-20 w-52 rounded-xl bg-white shadow-lift border border-slate-100 py-1 text-left" onClick={(e) => e.stopPropagation()}>
                              <MenuItem onClick={() => { setMenu(null); rename(d); }}>Rename</MenuItem>
                              <MenuItem onClick={() => { setMenu(null); run(() => api(`/api/documents/${d.id}/duplicate`, { method: "POST" }), "Duplicated"); }}><Copy className="h-3.5 w-3.5" />Duplicate</MenuItem>
                              <div className="px-3 pt-2 pb-1 text-[11px] uppercase tracking-wide text-slate-400">Move to folder</div>
                              <MenuItem onClick={() => { setMenu(null); run(() => api(`/api/documents/${d.id}`, { method: "PATCH", body: { folder_id: null } })); }}>— No folder —</MenuItem>
                              {folders.map((f) => <MenuItem key={f.id} onClick={() => { setMenu(null); run(() => api(`/api/documents/${d.id}`, { method: "PATCH", body: { folder_id: f.id } }), `Moved to ${f.name}`); }}><Folder className="h-3.5 w-3.5" />{f.name}</MenuItem>)}
                              <div className="border-t border-slate-100 my-1" />
                              <MenuItem danger onClick={() => { setMenu(null); trash(d); }}><Trash2 className="h-3.5 w-3.5" />Move to trash</MenuItem>
                            </div>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </div>
  );
}

function MenuItem({ children, onClick, danger }: { children: React.ReactNode; onClick: () => void; danger?: boolean }) {
  return <button onClick={onClick} className={cx("w-full flex items-center gap-2 px-3 py-1.5 text-sm text-left hover:bg-slate-50", danger ? "text-brandred-600" : "text-slate-700")}>{children}</button>;
}
