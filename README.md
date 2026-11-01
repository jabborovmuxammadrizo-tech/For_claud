# PDF Test Designer — Mirzo Ulugbek NTM

A Windows desktop application that turns an existing examination (PDF, DOCX, TXT or a scanned
image) into a branded, print-ready PDF in one click — while preserving every question, answer
option, table and image exactly as written.

**Upload → choose a saved template → ONE-CLICK GENERATE.** Analysis, extraction, template
application, pagination, quality control and export are automatic. A full visual editor is
available when manual changes are wanted, and the same actions work from the Windows File
Explorer right-click menu.

| | |
|---|---|
| Installer | `PDF_Test_Designer_Setup.exe` (NSIS, Windows 10/11 x64, all users, Program Files) |
| Portable | `PDF_Test_Designer_Portable.zip` and `PDF_Test_Designer_Standalone.exe` |
| Requirements | none — Python, Node.js and OCR are bundled; works fully offline |
| Data folder | `Documents\PDF Test Designer\` (documents, templates, images, fonts, exports, backups, logs) |

The installers are built and tested on a clean `windows-latest` machine by
[`.github/workflows/windows-build.yml`](.github/workflows/windows-build.yml) and attached to each
run as artifacts.

## Repository layout

```
backend/            Python processing engine (FastAPI on 127.0.0.1, token protected)
  ptd/importers/    PDF / DOCX / TXT / image extraction, structure detection, offline OCR
  ptd/layout/       ReportLab layout engine, fonts, original-page (Mode B) renderer
  ptd/pipeline.py   six-step one-click pipeline with real progress
  ptd/validation.py source → model → PDF content and layout checks, auto-repair hints
  ptd/shell.py      Windows Explorer right-click processing engine
  tests/            65 tests over realistic exam fixtures (network access blocked)
  ptd-backend.spec  PyInstaller build of the standalone engine
frontend/           Electron + React + TypeScript + Tailwind desktop UI
  electron/         secure main process, preload bridge, Explorer registry integration
  src/pages/        Dashboard, Quick Generator, Documents, Import, Editor, Templates,
                    Branding, Image Library, Fonts, Batch, Settings, right-click Task window
  build/            icons and the generated NSIS include (context menus)
samples/templates/  the nine built-in templates as importable .ptdtemplate.json files
docs/               user manual, build guide, Windows integration, test report
```

## Documentation

* [User manual](docs/USER_MANUAL.md)
* [Build instructions](docs/BUILD.md)
* [Windows Explorer integration](docs/WINDOWS_INTEGRATION.md)
* [Test report](docs/TEST_REPORT.md)
