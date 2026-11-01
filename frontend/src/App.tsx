import {
  Building2, FileStack, FileUp, FolderOpen, Image as ImageIcon, LayoutDashboard, LayoutTemplate, PenTool, Settings as SettingsIcon, Type, Zap,
} from "lucide-react";
import React, { useEffect, useState } from "react";
import { api, initApi } from "./api";
import { cx, DialogProvider, Spinner, ToastProvider } from "./components/ui";
import Batch from "./pages/Batch";
import BrandingPage from "./pages/Branding";
import Dashboard from "./pages/Dashboard";
import Documents from "./pages/Documents";
import Editor from "./pages/Editor";
import Fonts from "./pages/Fonts";
import ImageLibrary from "./pages/Images";
import ImportPage from "./pages/Import";
import QuickGenerator from "./pages/QuickGenerator";
import SettingsPage from "./pages/Settings";
import TaskPage from "./pages/Task";
import TemplatesPage from "./pages/Templates";

export type Route = { page: string; id?: string; params: URLSearchParams };

export function parseHash(): Route {
  const h = location.hash.replace(/^#\/?/, "");
  const [path, qs] = h.split("?");
  const [page, id] = path.split("/");
  return { page: page || "dashboard", id, params: new URLSearchParams(qs || "") };
}
export function navigate(to: string) { location.hash = "#/" + to.replace(/^\/+/, ""); }

const NAV = [
  { key: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { key: "quick", label: "Quick Generator", icon: Zap, hero: true },
  { key: "documents", label: "My Documents", icon: FolderOpen },
  { key: "import", label: "PDF Import", icon: FileUp },
  { key: "editor", label: "Document Editor", icon: PenTool },
  { key: "templates", label: "Templates", icon: LayoutTemplate },
  { key: "branding", label: "Organization Branding", icon: Building2 },
  { key: "images", label: "Image Library", icon: ImageIcon },
  { key: "fonts", label: "Font Manager", icon: Type },
  { key: "batch", label: "Batch Generator", icon: FileStack },
  { key: "settings", label: "Settings", icon: SettingsIcon },
];

function Sidebar({ current }: { current: string }) {
  return (
    <aside className="w-[248px] shrink-0 bg-navy-900 text-white flex flex-col">
      <div className="px-5 pt-5 pb-6 flex items-center gap-3">
        <div className="h-11 w-11 rounded-full bg-white flex items-center justify-center shadow-lift p-0.5"><img src="./logo.svg" alt="Mirzo Ulugbek NTM" className="h-full w-full" /></div>
        <div className="leading-tight">
          <div className="font-bold text-[15px]">PDF Test Designer</div>
          <div className="text-[11px] text-white/60 tracking-wide">MIRZO ULUGBEK NTM</div>
        </div>
      </div>
      <nav className="flex-1 px-3 space-y-0.5 overflow-auto">
        {NAV.map((n) => {
          const active = current === n.key;
          const Icon = n.icon;
          return (
            <a key={n.key} href={`#/${n.key}`}
              className={cx("flex items-center gap-3 rounded-lg px-3 py-2.5 text-[13.5px] transition-colors",
                n.hero && !active && "bg-white/[.06] text-white font-semibold ring-1 ring-white/10 my-1.5",
                active ? "bg-royal-600 text-white font-semibold shadow-sm" : !n.hero && "text-white/70 hover:bg-white/[.07] hover:text-white")}>
              <Icon className={cx("h-[18px] w-[18px]", n.hero && !active && "text-amber-300")} />
              {n.label}
            </a>
          );
        })}
      </nav>
      <div className="px-5 py-4 text-[11px] text-white/40 border-t border-white/10">Offline · all files stay on this computer</div>
    </aside>
  );
}

export default function App() {
  const [route, setRoute] = useState<Route>(parseHash());
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const h = () => setRoute(parseHash());
    window.addEventListener("hashchange", h);
    const off = window.ptd?.onNavigate((hash) => navigate(hash));
    initApi().then(async () => {
      for (let i = 0; i < 40; i++) {
        try { await api("/api/info"); setReady(true); return; } catch { await new Promise((r) => setTimeout(r, 250)); }
      }
      setError("The processing engine is not responding. Restart the application; if the problem continues, check the logs in Settings.");
    });
    return () => { window.removeEventListener("hashchange", h); off?.(); };
  }, []);

  let body: React.ReactNode;
  if (error) body = <div className="p-10 text-brandred-700">{error}</div>;
  else if (!ready) body = <div className="flex h-full items-center justify-center"><Spinner className="h-8 w-8" /></div>;
  else {
    const P = {
      dashboard: Dashboard, quick: QuickGenerator, documents: Documents, import: ImportPage, editor: Editor, templates: TemplatesPage,
      branding: BrandingPage, images: ImageLibrary, fonts: Fonts, batch: Batch, settings: SettingsPage,
    }[route.page] || Dashboard;
    body = <P route={route} />;
  }
  if (route.page === "task") {
    return <ToastProvider><DialogProvider>{ready ? <TaskPage route={route} /> : <div className="flex h-screen items-center justify-center">{error || <Spinner className="h-8 w-8" />}</div>}</DialogProvider></ToastProvider>;
  }
  const full = route.page === "editor" && !!route.id;
  return (
    <ToastProvider>
      <DialogProvider>
        <div className="flex h-screen w-screen overflow-hidden text-slate-800">
          <Sidebar current={route.page} />
          <main className={cx("flex-1 min-w-0 overflow-auto", full ? "" : "px-8 py-7")}>
            <div className={cx(full ? "h-full" : "max-w-[1400px] mx-auto")}>{body}</div>
          </main>
        </div>
      </DialogProvider>
    </ToastProvider>
  );
}
