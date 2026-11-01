# Building PDF Test Designer

The release build has two parts: the Python processing engine, frozen with PyInstaller into
`ptd-backend.exe`, and the Electron desktop application, packaged with electron-builder (NSIS).
The engine is copied into the application's `resources\backend` folder, so end users need
neither Python nor Node.js.

## Automated build (recommended)

Every push runs [`.github/workflows/windows-build.yml`](../.github/workflows/windows-build.yml) on
`windows-latest`. The workflow:

1. runs the backend test suite on Windows;
2. builds `ptd-backend.exe` and self-tests it with Python removed from `PATH`;
3. builds the Electron app and the installers;
4. installs `PDF_Test_Designer_Setup.exe` silently, checks the Explorer context-menu registry
   entries and runs the exact command lines Explorer uses (Uzbek, space-containing and very long
   file names, multi-select, folders);
5. uninstalls, then confirms the registry is clean and user documents are still present;
6. uploads `PDF_Test_Designer_Setup.exe`, `PDF_Test_Designer_Portable.zip`,
   `PDF_Test_Designer_Standalone.exe` and the test logs/outputs as artifacts.

Download the artifacts from the run's **Summary** page.

## Manual build on Windows 10/11 (x64)

Prerequisites: Python 3.13 (64-bit), Node.js 22, Git.

```powershell
git clone https://github.com/jabborovmuxammadrizo-tech/For_claud.git
cd For_claud

# 1. engine
cd backend
python -m pip install -r requirements-dev.txt
python -m pytest -q tests                      # optional, ~2 minutes
pyinstaller --noconfirm ptd-backend.spec       # -> backend\dist\ptd-backend\ptd-backend.exe
cd ..

# 2. desktop application + installers
cd frontend
mkdir backend-dist
xcopy /E /I ..\backend\dist\ptd-backend backend-dist\ptd-backend
npm ci
npm run dist:win                               # -> frontend\release\
```

`frontend\release\` then contains:

| File | Purpose |
|---|---|
| `PDF_Test_Designer_Setup.exe` | installation wizard: directory choice, Program Files, desktop + Start-menu shortcuts, Explorer menus, uninstaller, launch after install |
| `PDF_Test_Designer_Portable.zip` | unzip and run `PDF Test Designer.exe` (Explorer menus can be enabled per user from Settings) |
| `PDF_Test_Designer_Standalone.exe` | single-file portable executable |

### Code signing

The build is unsigned, so Windows SmartScreen shows "Windows protected your PC" on first run
(choose **More info → Run anyway**). For distribution, set electron-builder's `CSC_LINK` /
`CSC_KEY_PASSWORD` environment variables to an Authenticode certificate before
`npm run dist:win`, and sign `ptd-backend.exe` with `signtool` before packaging.

## Development

```bash
# backend only
cd backend && python -m pip install -r requirements-dev.txt
PTD_TOKEN=dev python run_backend.py --port 8765 --dev

# desktop app with hot reload (starts the backend from ../backend with your Python)
cd frontend && npm ci && npm run dev
```

The Explorer context menu is generated from `frontend/electron/shell-menus.json`:
`npm run gen:installer` regenerates `build/installer.nsh`. CI fails if the committed file is
out of date.

## Updating

Installing a newer `PDF_Test_Designer_Setup.exe` over an existing installation keeps all user
data. On first start the engine detects the version change and creates
`Backups\backup-…-before-upgrade-<old version>.zip` before touching any data. An optional update
check (Settings → Updates) reads a JSON file from a school-provided HTTPS address; the
application never depends on it.
