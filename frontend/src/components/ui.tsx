import { AlertTriangle, CheckCircle2, Info, Loader2, UploadCloud, X, XCircle } from "lucide-react";
import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

export function cx(...c: (string | false | null | undefined)[]) { return c.filter(Boolean).join(" "); }

type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger" | "hero"; size?: "sm" | "md" | "lg"; icon?: React.ReactNode; loading?: boolean };
export function Button({ variant = "secondary", size = "md", icon, loading, className, children, disabled, ...p }: BtnProps) {
  const v = {
    primary: "bg-royal-600 text-white hover:bg-royal-700 shadow-sm",
    hero: "bg-gradient-to-r from-royal-600 to-navy-700 text-white hover:from-royal-700 hover:to-navy-800 shadow-lift",
    secondary: "bg-white text-navy-900 border border-slate-200 hover:bg-slate-50 hover:border-slate-300",
    ghost: "text-slate-600 hover:bg-slate-100 hover:text-navy-900",
    danger: "bg-brandred-600 text-white hover:bg-brandred-700",
  }[variant];
  const s = { sm: "h-8 px-3 text-[13px] gap-1.5", md: "h-10 px-4 text-sm gap-2", lg: "h-14 px-8 text-base gap-3 font-semibold" }[size];
  return (
    <button {...p} disabled={disabled || loading}
      className={cx("inline-flex items-center justify-center rounded-lg font-medium transition-colors duration-150 disabled:opacity-50 disabled:cursor-not-allowed select-none whitespace-nowrap", v, s, className)}>
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

export function Card({ className, children, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  return <div {...p} className={cx("rounded-xl bg-white shadow-card border border-slate-100", className)}>{children}</div>;
}

export function SectionTitle({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: React.ReactNode }) {
  return (
    <div className="flex items-end justify-between gap-4 mb-5">
      <div>
        <h1 className="text-2xl font-bold text-navy-900 tracking-tight">{title}</h1>
        {subtitle && <p className="text-sm text-slate-500 mt-1">{subtitle}</p>}
      </div>
      {actions && <div className="flex gap-2 items-center">{actions}</div>}
    </div>
  );
}

export function Badge({ tone = "slate", children, className }: { tone?: "slate" | "blue" | "red" | "green" | "amber" | "navy"; children: React.ReactNode; className?: string }) {
  const t = {
    slate: "bg-slate-100 text-slate-700", blue: "bg-royal-50 text-royal-700", red: "bg-brandred-50 text-brandred-700",
    green: "bg-emerald-50 text-emerald-700", amber: "bg-amber-50 text-amber-800", navy: "bg-navy-900 text-white",
  }[tone];
  return <span className={cx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold", t, className)}>{children}</span>;
}

export function Progress({ value, tone = "blue", className }: { value: number; tone?: "blue" | "green" | "red" | "amber"; className?: string }) {
  const c = { blue: "bg-royal-600", green: "bg-emerald-500", red: "bg-brandred-600", amber: "bg-amber-500" }[tone];
  return (
    <div className={cx("h-2 w-full rounded-full bg-slate-100 overflow-hidden", className)}>
      <div className={cx("h-full rounded-full transition-[width] duration-300", c)} style={{ width: `${Math.max(0, Math.min(100, value * 100))}%` }} />
    </div>
  );
}

export function Spinner({ className }: { className?: string }) { return <Loader2 className={cx("h-5 w-5 animate-spin text-royal-600", className)} />; }

export function EmptyState({ icon, title, text, action }: { icon: React.ReactNode; title: string; text?: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-14 px-6">
      <div className="h-14 w-14 rounded-2xl bg-royal-50 text-royal-600 flex items-center justify-center mb-4">{icon}</div>
      <div className="font-semibold text-navy-900">{title}</div>
      {text && <div className="text-sm text-slate-500 mt-1 max-w-md">{text}</div>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Modal({ open, onClose, title, children, footer, width = "max-w-lg" }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode; footer?: React.ReactNode; width?: string }) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-navy-950/50 p-6" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className={cx("w-full rounded-2xl bg-white shadow-lift flex flex-col max-h-[92vh]", width)} role="dialog" aria-modal="true" aria-label={title}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
          <h3 className="font-semibold text-navy-900">{title}</h3>
          <button className="p-1 rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-700" onClick={onClose} aria-label="Close"><X className="h-5 w-5" /></button>
        </div>
        <div className="px-6 py-5 overflow-auto">{children}</div>
        {footer && <div className="flex justify-end gap-2 px-6 py-4 border-t border-slate-100 bg-slate-50/60 rounded-b-2xl">{footer}</div>}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ confirm + prompt
type ConfirmOpts = { title: string; message: React.ReactNode; confirmText?: string; danger?: boolean; requireText?: string };
type PromptOpts = { title: string; label: string; initial?: string; confirmText?: string };
const DialogCtx = createContext<{ confirm: (o: ConfirmOpts) => Promise<boolean>; prompt: (o: PromptOpts) => Promise<string | null> }>({
  confirm: async () => false, prompt: async () => null,
});
export const useDialogs = () => useContext(DialogCtx);

export function DialogProvider({ children }: { children: React.ReactNode }) {
  const [c, setC] = useState<(ConfirmOpts & { resolve: (v: boolean) => void }) | null>(null);
  const [p, setP] = useState<(PromptOpts & { resolve: (v: string | null) => void }) | null>(null);
  const [typed, setTyped] = useState("");
  const [val, setVal] = useState("");
  const confirm = useCallback((o: ConfirmOpts) => new Promise<boolean>((resolve) => { setTyped(""); setC({ ...o, resolve }); }), []);
  const prompt = useCallback((o: PromptOpts) => new Promise<string | null>((resolve) => { setVal(o.initial || ""); setP({ ...o, resolve }); }), []);
  return (
    <DialogCtx.Provider value={{ confirm, prompt }}>
      {children}
      <Modal open={!!c} title={c?.title || ""} onClose={() => { c?.resolve(false); setC(null); }}
        footer={<>
          <Button onClick={() => { c?.resolve(false); setC(null); }}>Cancel</Button>
          <Button variant={c?.danger ? "danger" : "primary"} disabled={!!c?.requireText && typed !== c.requireText}
            onClick={() => { c?.resolve(true); setC(null); }}>{c?.confirmText || "Confirm"}</Button>
        </>}>
        <div className="text-sm text-slate-600 leading-relaxed">{c?.message}</div>
        {c?.requireText && (
          <div className="mt-4">
            <Label>Type <b className="text-navy-900">{c.requireText}</b> to confirm</Label>
            <TextInput autoFocus value={typed} onChange={(e) => setTyped(e.target.value)} />
          </div>
        )}
      </Modal>
      <Modal open={!!p} title={p?.title || ""} onClose={() => { p?.resolve(null); setP(null); }}
        footer={<>
          <Button onClick={() => { p?.resolve(null); setP(null); }}>Cancel</Button>
          <Button variant="primary" disabled={!val.trim()} onClick={() => { p?.resolve(val.trim()); setP(null); }}>{p?.confirmText || "OK"}</Button>
        </>}>
        <Label>{p?.label}</Label>
        <TextInput autoFocus value={val} onChange={(e) => setVal(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && val.trim()) { p?.resolve(val.trim()); setP(null); } }} />
      </Modal>
    </DialogCtx.Provider>
  );
}

// ------------------------------------------------------------------ toasts
type Toast = { id: number; tone: "success" | "error" | "info" | "warning"; text: string };
const ToastCtx = createContext<(tone: Toast["tone"], text: string) => void>(() => {});
export const useToast = () => useContext(ToastCtx);
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const n = useRef(0);
  const push = useCallback((tone: Toast["tone"], text: string) => {
    const id = ++n.current;
    setItems((x) => [...x, { id, tone, text }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), tone === "error" ? 9000 : 4500);
  }, []);
  const icon = { success: <CheckCircle2 className="h-5 w-5 text-emerald-500" />, error: <XCircle className="h-5 w-5 text-brandred-600" />,
    info: <Info className="h-5 w-5 text-royal-600" />, warning: <AlertTriangle className="h-5 w-5 text-amber-500" /> };
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="fixed bottom-5 right-5 z-[60] flex flex-col gap-2 w-[380px]">
        {items.map((t) => (
          <div key={t.id} className="flex items-start gap-3 rounded-xl bg-white shadow-lift border border-slate-100 px-4 py-3 text-sm text-slate-700 animate-[fadein_.2s_ease-out]">
            {icon[t.tone]}<div className="flex-1 leading-snug">{t.text}</div>
            <button onClick={() => setItems((x) => x.filter((y) => y.id !== t.id))} className="text-slate-400 hover:text-slate-600" aria-label="Dismiss"><X className="h-4 w-4" /></button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

// ------------------------------------------------------------------ form fields
export function Label({ children, hint }: { children: React.ReactNode; hint?: string }) {
  return <label className="block text-[12px] font-semibold text-slate-600 mb-1" title={hint}>{children}{hint && <span className="ml-1 text-slate-400 cursor-help" aria-label={hint}>ⓘ</span>}</label>;
}
export const TextInput = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(function TextInput({ className, ...p }, ref) {
  return <input ref={ref} {...p} className={cx("h-9 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-navy-900 outline-none focus:border-royal-500 focus:ring-2 focus:ring-royal-100 placeholder:text-slate-400", className)} />;
});
export function TextArea({ className, ...p }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...p} className={cx("w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-navy-900 outline-none focus:border-royal-500 focus:ring-2 focus:ring-royal-100 leading-relaxed", className)} />;
}
export function Select({ value, onChange, options, className, ...p }: { value: string | number | undefined | null; onChange: (v: string) => void; options: { value: string; label: string }[]; className?: string } & Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "onChange" | "value">) {
  return (
    <select {...p} value={value ?? ""} onChange={(e) => onChange(e.target.value)}
      className={cx("h-9 w-full rounded-lg border border-slate-200 bg-white px-2.5 text-sm text-navy-900 outline-none focus:border-royal-500 focus:ring-2 focus:ring-royal-100", className)}>
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}
export function NumberInput({ value, onChange, min, max, step = 1, className, placeholder }: { value: number | undefined | null; onChange: (v: number | null) => void; min?: number; max?: number; step?: number; className?: string; placeholder?: string }) {
  return <TextInput type="number" className={className} value={value ?? ""} min={min} max={max} step={step} placeholder={placeholder}
    onChange={(e) => { const v = e.target.value; onChange(v === "" ? null : Math.max(min ?? -1e9, Math.min(max ?? 1e9, Number(v)))); }} />;
}
export function ColorInput({ value, onChange }: { value: string | null | undefined; onChange: (v: string) => void }) {
  return (
    <div className="flex items-center gap-2">
      <input type="color" value={value || "#000000"} onChange={(e) => onChange(e.target.value.toUpperCase())} className="h-9 w-11 rounded-lg border border-slate-200 bg-white p-1 cursor-pointer" />
      <TextInput value={value || ""} onChange={(e) => onChange(e.target.value)} className="font-mono uppercase" placeholder="#RRGGBB" />
    </div>
  );
}
export function Toggle({ checked, onChange, label, hint }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string }) {
  return (
    <label className="flex items-center justify-between gap-3 py-1.5 cursor-pointer select-none" title={hint}>
      <span className="text-sm text-slate-700">{label}</span>
      <button type="button" role="switch" aria-checked={checked} onClick={() => onChange(!checked)}
        className={cx("relative h-5 w-9 shrink-0 rounded-full transition-colors", checked ? "bg-royal-600" : "bg-slate-300")}>
        <span className={cx("absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all", checked ? "left-[18px]" : "left-0.5")} />
      </button>
    </label>
  );
}
export function Slider({ value, onChange, min, max, step = 0.01, format }: { value: number; onChange: (v: number) => void; min: number; max: number; step?: number; format?: (v: number) => string }) {
  return (
    <div className="flex items-center gap-3">
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} className="flex-1 accent-royal-600" />
      <span className="w-12 text-right text-xs tabular-nums text-slate-600">{format ? format(value) : value}</span>
    </div>
  );
}
export function Field({ label, hint, children, className }: { label: string; hint?: string; children: React.ReactNode; className?: string }) {
  return <div className={className}><Label hint={hint}>{label}</Label>{children}</div>;
}

// ------------------------------------------------------------------ dropzone
export function Dropzone({ onFiles, accept, multiple, title, subtitle, compact }: { onFiles: (f: File[]) => void; accept: string; multiple?: boolean; title: string; subtitle?: string; compact?: boolean }) {
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); const f = Array.from(e.dataTransfer.files); if (f.length) onFiles(multiple ? f : f.slice(0, 1)); }}
      onClick={() => input.current?.click()}
      role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") input.current?.click(); }}
      className={cx("cursor-pointer rounded-2xl border-2 border-dashed transition-colors flex flex-col items-center justify-center text-center",
        compact ? "px-5 py-6" : "px-8 py-12", over ? "border-royal-500 bg-royal-50" : "border-slate-300 bg-slate-50/60 hover:border-royal-400 hover:bg-royal-50/40")}>
      <div className={cx("rounded-2xl bg-white shadow-card flex items-center justify-center text-royal-600", compact ? "h-11 w-11 mb-2" : "h-16 w-16 mb-4")}><UploadCloud className={compact ? "h-6 w-6" : "h-8 w-8"} /></div>
      <div className="font-semibold text-navy-900">{title}</div>
      {subtitle && <div className="text-sm text-slate-500 mt-1">{subtitle}</div>}
      <input ref={input} type="file" accept={accept} multiple={multiple} className="hidden"
        onChange={(e) => { const f = Array.from(e.target.files || []); if (f.length) onFiles(f); e.target.value = ""; }} />
    </div>
  );
}

export function IssueIcon({ level, className }: { level: string; className?: string }) {
  if (level === "critical") return <XCircle className={cx("h-4 w-4 text-brandred-600 shrink-0", className)} />;
  if (level === "warning") return <AlertTriangle className={cx("h-4 w-4 text-amber-500 shrink-0", className)} />;
  return <Info className={cx("h-4 w-4 text-royal-500 shrink-0", className)} />;
}

export function fmtBytes(n: number | null | undefined) {
  if (!n && n !== 0) return "—";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0, v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${u[i]}`;
}
export function fmtDate(ts: number | null | undefined) {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  return d.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" }) + " " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}
export function errMsg(e: unknown) { return e instanceof Error ? e.message : String(e); }
