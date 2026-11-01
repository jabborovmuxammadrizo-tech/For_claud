# PyInstaller spec for the standalone processing engine (ptd-backend.exe).
# Build:  pyinstaller --noconfirm ptd-backend.spec   ->  dist/ptd-backend/ptd-backend.exe
# The Electron app starts it hidden (windowsHide) and talks to it over 127.0.0.1 with a secret token.
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

hidden = (
    collect_submodules("uvicorn")
    + collect_submodules("rapidocr_onnxruntime")
    + ["ptd.importers.pdf_import", "ptd.importers.docx_import", "ptd.importers.simple_import", "multipart", "python_multipart"]
)
datas = [("resources", "resources")]
for pkg in ("rapidocr_onnxruntime", "docx", "reportlab", "pdfminer", "pdfplumber", "pymupdf"):
    datas += collect_data_files(pkg)
binaries = collect_dynamic_libs("onnxruntime") + collect_dynamic_libs("pymupdf")

a = Analysis(
    ["run_backend.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=["tkinter", "matplotlib", "pytest", "IPython", "notebook", "PyQt5", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ptd-backend",
    console=True,          # stdout is needed for the readiness handshake; Electron hides the window
    icon="../frontend/build/icon.ico",
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="ptd-backend")
