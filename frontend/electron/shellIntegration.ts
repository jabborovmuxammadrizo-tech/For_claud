/**
 * Windows Explorer context-menu registration for the current user (no administrator rights needed).
 *  - The installer registers the menus for all users (HKLM, see build/installer.nsh).
 *  - Per-user enable/disable toggles are HKCU overrides with the documented "LegacyDisable" value,
 *    which hides a static verb without touching the machine-wide registration.
 *  - The portable version can register the same menus in HKCU.
 * All writes go through one generated .reg file imported with reg.exe (no shell, no string concatenation
 * into command lines).
 */
import { execFile } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
// eslint-disable-next-line @typescript-eslint/no-var-requires
const { buildEntries, ownedKeys, menus } = require("./shell-entries.cjs");

type Entry = { path: string; values: Record<string, string>; group: string; item?: string; setting?: string; shared?: boolean };
const HKCU = "HKEY_CURRENT_USER\\Software\\Classes";
const HKLM = "HKEY_LOCAL_MACHINE\\Software\\Classes";

const regStr = (s: string) => s.replace(/\\/g, "\\\\").replace(/"/g, '\\"');

function run(args: string[]): Promise<{ code: number; out: string }> {
  return new Promise((resolve) => {
    execFile("reg.exe", args, { windowsHide: true }, (err, stdout, stderr) => {
      resolve({ code: err ? (typeof (err as any).code === "number" ? (err as any).code : 1) : 0, out: `${stdout}${stderr}` });
    });
  });
}

async function importReg(lines: string[]) {
  const file = path.join(os.tmpdir(), `ptd-shell-${process.pid}-${Date.now()}.reg`);
  const body = "Windows Registry Editor Version 5.00\r\n\r\n" + lines.join("\r\n") + "\r\n";
  fs.writeFileSync(file, Buffer.concat([Buffer.from([0xff, 0xfe]), Buffer.from(body, "utf16le")]));
  try {
    const r = await run(["import", file]);
    if (r.code !== 0) throw new Error(`Windows refused the registry change: ${r.out.trim()}`);
  } finally {
    fs.rmSync(file, { force: true });
  }
}

function valueLine(name: string, value: string) {
  const n = name === "" ? "@" : `"${regStr(name)}"`;
  return value.startsWith("dword:") ? `${n}=${value}` : `${n}="${regStr(value)}"`;
}

export const supported = () => process.platform === "win32";

export async function status() {
  if (!supported()) return { platform: process.platform, machine: false, user: false };
  const key = `\\SystemFileAssociations\\.pdf\\shell\\${menus.verbKey}`;
  const [m, u] = await Promise.all([run(["query", HKLM + key, "/v", "MUIVerb"]), run(["query", HKCU + key, "/v", "MUIVerb"])]);
  return { platform: process.platform, machine: m.code === 0, user: u.code === 0 };
}

/** Register all menus for the current user (portable mode or repair). */
export async function registerUser(exe: string) {
  const lines: string[] = [];
  for (const k of ownedKeys()) lines.push(`[-${HKCU}\\${k}]`, "");
  for (const e of buildEntries(exe) as Entry[]) {
    lines.push(`[${HKCU}\\${e.path}]`);
    for (const [n, v] of Object.entries(e.values)) lines.push(valueLine(n, v));
    lines.push("");
  }
  await importReg(lines);
}

export async function unregisterUser() {
  const lines: string[] = [];
  for (const k of ownedKeys()) lines.push(`[-${HKCU}\\${k}]`, "");
  for (const ext of menus.openWithExtensions) lines.push(`[${HKCU}\\${ext}\\OpenWithProgids]`, `"${menus.progId}"=-`, "");
  await importReg(lines);
}

/** Apply the enable/disable switches from Settings → Windows Integration. */
export async function applyToggles(settings: Record<string, unknown>, exe: string) {
  const st = await status();
  const lines: string[] = [];
  const seen = new Set<string>();
  for (const e of buildEntries(exe) as Entry[]) {
    if (e.group === "assoc" || e.path.endsWith("\\command") || seen.has(e.path)) continue;
    seen.add(e.path);
    const isRoot = !e.item;
    const disabled = settings[isRoot ? (menus.groups.find((g: any) => g.id === e.group)?.setting) : e.setting || ""] === false;
    if (isRoot || e.setting) {
      lines.push(`[${HKCU}\\${e.path}]`, disabled ? `"LegacyDisable"=""` : `"LegacyDisable"=-`, "");
    }
  }
  if (!st.machine && !st.user) await registerUser(exe);
  await importReg(lines);
}

/** Remove user overrides; re-create the per-user registration when there is no machine-wide one. */
export async function restoreDefaults(exe: string) {
  const st = await status();
  if (st.machine) {
    const lines: string[] = [];
    for (const k of ownedKeys()) lines.push(`[-${HKCU}\\${k}]`, "");
    await importReg(lines);
  } else {
    await registerUser(exe);
  }
}
