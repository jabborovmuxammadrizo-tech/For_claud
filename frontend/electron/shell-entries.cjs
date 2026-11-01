// Builds the Windows Explorer registry entries from shell-menus.json.
// Used by the app (per-user registration / toggles) and by scripts/gen-installer-nsh.mjs (installer).
// Static shell verbs with cascading submenus: SubCommands="" + nested "shell" keys (Windows 7+).
const menus = require("./shell-menus.json");

/**
 * @param {string} exe   full path of the application executable, or an NSIS expression
 * @returns {{path: string, values: Record<string,string>, group: string, item?: string, setting?: string}[]}
 *          paths are relative to Software\Classes
 */
function buildEntries(exe) {
  const out = [];
  const icon = `"${exe}",0`;
  for (const g of menus.groups) {
    for (const root of g.roots) {
      const base = `${root}\\shell\\${menus.verbKey}`;
      out.push({ path: base, group: g.id, setting: g.setting,
        values: { MUIVerb: menus.title, Icon: icon, SubCommands: "", MultiSelectModel: "Player" } });
      for (const it of g.items) {
        const values = { MUIVerb: it.label, Icon: icon, MultiSelectModel: "Player" };
        if (it.separatorBefore) values.CommandFlags = "dword:00000020"; // ECF_SEPARATORBEFORE
        out.push({ path: `${base}\\shell\\${it.key}`, group: g.id, item: it.key, setting: it.setting, values });
        out.push({ path: `${base}\\shell\\${it.key}\\command`, group: g.id, item: it.key,
          values: { "": `"${exe}" ${it.args} "%1"` } });
      }
    }
  }
  // "Open with" registration that never replaces the user's default PDF/Word application
  out.push({ path: menus.progId, group: "assoc", values: { "": "PDF Test Designer document", FriendlyTypeName: "PDF Test Designer document" } });
  out.push({ path: `${menus.progId}\\DefaultIcon`, group: "assoc", values: { "": icon } });
  out.push({ path: `${menus.progId}\\shell\\open\\command`, group: "assoc", values: { "": `"${exe}" --shell=open "%1"` } });
  for (const ext of menus.openWithExtensions) {
    out.push({ path: `${ext}\\OpenWithProgids`, group: "assoc", values: { [menus.progId]: "" }, shared: true });
  }
  return out;
}

/** Top-level keys owned by the application (deleted on uninstall / unregister). */
function ownedKeys() {
  const keys = [];
  for (const g of menus.groups) for (const root of g.roots) keys.push(`${root}\\shell\\${menus.verbKey}`);
  keys.push(menus.progId);
  return keys;
}

module.exports = { buildEntries, ownedKeys, menus };
