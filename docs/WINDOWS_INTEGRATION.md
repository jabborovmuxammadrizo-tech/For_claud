# Windows File Explorer integration (Part 25)

## Mechanism

PDF Test Designer uses **registered static shell verbs with cascading submenus**: a verb with
`SubCommands=""` and nested `shell\<item>\command` keys, supported since Windows 7. This is
Microsoft's documented, declarative mechanism. No shell-extension DLL is loaded into Explorer,
so opening the menu costs nothing (no file is read or parsed) and Explorer can never crash
because of the application.

| Selection | Registry location (under `Software\Classes`) |
|---|---|
| PDF | `SystemFileAssociations\.pdf\shell\PDFTestDesigner` |
| DOCX | `SystemFileAssociations\.docx\shell\PDFTestDesigner` |
| Folder | `Directory\shell\PDFTestDesigner` |
| Images | `SystemFileAssociations\.png/.jpg/.jpeg/.bmp/.tif/.tiff\shell\PDFTestDesigner` |
| Open with | ProgID `PDFTestDesigner.Document` + `OpenWithProgids` for .pdf/.docx/.txt — the user's default PDF or Word application is **not** changed |

`SystemFileAssociations` is used so the menu appears whatever program owns `.pdf`. Each item's
command is

```
"C:\Program Files\PDF Test Designer\PDF Test Designer.exe" --shell=<command> "%1"
```

Explorer quotes the path, so spaces, Unicode (Uzbek) characters and long paths are passed
intact. Only absolute paths of existing files are accepted.

The single source of truth is `frontend/electron/shell-menus.json`:

* `scripts/gen-installer-nsh.mjs` turns it into `build/installer.nsh`. The installer writes the
  keys for all users (HKLM) and the uninstaller deletes **only** the application-owned keys.
  User documents, templates and exports are never touched.
* `electron/shellIntegration.ts` uses the same definitions for the per-user features below.

### Windows 11

Static verbs appear in the classic menu: **Show more options**, or Shift + right-click. Adding
entries to the new top-level Windows 11 menu requires a signed sparse MSIX package with a COM
`IExplorerCommand` DLL. That needs a code-signing certificate, which this project does not yet
have, so it is deliberately not included. The verbs work identically on Windows 10 and 11.

## Processing engine

1. Explorer starts one process per selected item. The first process takes Electron's
   single-instance lock. The others forward their arguments to it and exit immediately.
   Requests with the same command that arrive within 0.9 s are merged into **one task**, so a
   multi-selection becomes one batch. An identical request within 20 s is ignored, which
   prevents duplicate processing.
2. The running app (started in the background if it was closed) calls the local engine
   (`POST /api/shell/run`, loopback only, per-launch secret token). No additional network
   service is opened.
3. Each file becomes an independent job. A failure is recorded for that file only. Queued jobs
   can be cancelled, and running jobs stop at the next step boundary.
4. A compact task window shows progress per file and, when done, offers **Open generated
   file**, **Open output folder** and **View processing report**. A Windows notification is shown
   only after the files have been written **and** validated.

Commands: `generate-default`, `generate-template`, `batch-generate` (`--pick-template`), `open`,
`edit`, `open-folder`, `extract`, `convert-editable`, `convert-pdf`, `compress`, `grayscale`,
`info`, `image-library`, `image-pdf`, `image-editor`, `image-background`, `image-watermark`.

## Settings → Windows Integration

* Enable or disable the PDF, DOCX, folder and image menus, the batch entries and the default
  template action. These are written as per-user `LegacyDisable` values in HKCU, which hide a
  verb without needing administrator rights or modifying the machine-wide registration.
* Background processing (task window only) or open the main window.
* Completion notifications; include subfolders; ZIP of batch results.
* The template used for right-click generation.
* Output folder (default `Documents\PDF Test Designer\Exports`) and naming:
  `OriginalName_Formatted.pdf`, `OriginalName_Exam.pdf` or a custom pattern with `{name}`,
  `{template}`, `{date}`, `{time}`. Existing files are never overwritten: ` (2)`, ` (3)`… is
  added.
* **Restore default integration** removes all per-user overrides. The portable version can
  **Register for my account**, which writes the same menus under HKCU.

## Tests

* Linux, in `backend/tests/test_shell.py`: Uzbek and space-containing names, very long names,
  mixed multi-select with a picked template, folders with and without subfolders, failure
  isolation, compress, grayscale (verified pixel-gray, text still searchable), info, extract,
  convert to DOCX/PDF, image actions, unsupported formats, missing template, unavailable output
  folder, naming patterns, cancellation, API validation.
* Real Electron under Xvfb: a second `--shell` process forwards its file to the first; one
  background task generates both PDFs; no main window opens.
* Windows CI (`windows-build.yml`): silent install; registry verification; the exact Explorer
  command lines for a single file (application closed), multi-select (application running),
  a very long file name and a folder; silent uninstall verifying the keys are removed and user
  data is kept.
