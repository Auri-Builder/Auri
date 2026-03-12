# auri.spec — PyInstaller spec for Auri
# Run on Windows: pyinstaller auri.spec
# Requires: pip install pyinstaller==6.13.0
import sys
import os
from pathlib import Path
import streamlit
from PyInstaller.utils.hooks import copy_metadata, collect_data_files

ST_PKG = Path(streamlit.__file__).parent
PROJ = Path(SPECPATH)

# Package metadata required by importlib.metadata at runtime
_metadata = []
for _pkg in ["streamlit", "altair", "pandas", "numpy", "pyarrow",
             "plotly", "pydeck", "requests", "click", "packaging",
             "pillow", "pydantic", "watchdog", "tornado", "protobuf",
             "rich", "narwhals", "gitpython"]:
    try:
        _metadata += copy_metadata(_pkg)
    except Exception:
        pass

added_files = _metadata + [
    (str(PROJ / "Home.py"),        "."),
    (str(PROJ / "pages"),          "pages"),
    (str(PROJ / "agents"),         "agents"),
    (str(PROJ / "core"),           "core"),
    (str(PROJ / "refs"),           "refs"),
    (str(PROJ / "data" / "portfolio" / "questions.yaml"), "data/portfolio"),
    (str(PROJ / ".streamlit"),     ".streamlit"),
    (str(ST_PKG / "static"),       "streamlit/static"),
    (str(ST_PKG / "vendor"),       "streamlit/vendor"),
    (str(ST_PKG / "proto"),        "streamlit/proto"),
    (str(ST_PKG / "web"),          "streamlit/web"),
    (str(ST_PKG / "runtime"),      "streamlit/runtime"),
]

hidden_imports = [
    "streamlit", "streamlit.web.cli", "streamlit.web.bootstrap",
    "streamlit.web.server", "streamlit.web.server.starlette",
    "streamlit.runtime", "streamlit.runtime.caching",
    "streamlit.runtime.caching.storage",
    "streamlit.runtime.scriptrunner", "streamlit.runtime.state",
    "streamlit.components.v1", "streamlit.components.v2",
    "streamlit.elements", "streamlit.elements.lib",
    "streamlit.elements.widgets", "streamlit.watcher",
    "streamlit.vendor", "streamlit.vendor.pympler",
    "tornado", "tornado.platform.asyncio", "tornado.web",
    "tornado.httpserver", "tornado.websocket", "tornado.ioloop",
    "google.protobuf", "google.protobuf.descriptor",
    "google.protobuf.descriptor_pool", "google.protobuf.message",
    "google.protobuf.reflection", "google.protobuf.json_format",
    "openai", "httpx", "httpcore", "anyio",
    "anyio._backends._asyncio", "sniffio", "h11",
    "pydantic", "pydantic_core",
    "pandas", "pandas.core.arrays.arrow",
    "pyarrow", "pyarrow.lib",
    "numpy", "numpy.core", "numpy._core",
    "numpy._core._exceptions", "numpy._core._multiarray_umath",
    "numpy._core._multiarray_tests", "numpy._core.multiarray",
    "numpy._core.umath", "numpy._core.fromnumeric", "numpy._core.numeric",
    "numpy._core.numerictypes", "numpy._core.arrayprint",
    "numpy._core.defchararray", "numpy._core.records", "numpy._core.memmap",
    "numpy._core.function_base", "numpy._core.machar", "numpy._core.getlimits",
    "numpy._core.shape_base", "numpy._core.einsumfunc",
    "numpy._core._dtype_ctypes", "numpy._core._internal",
    "numpy.lib", "numpy.lib.stride_tricks", "numpy.linalg", "numpy.fft",
    "numpy.random", "numpy.polynomial",
    "plotly", "plotly.express", "plotly.graph_objects",
    "plotly.io", "plotly.io._renderers",
    "altair", "altair.vegalite", "narwhals", "narwhals.stable.v1",
    "yaml", "_yaml", "toml",
    "requests", "urllib3", "certifi", "charset_normalizer", "idna",
    "click", "packaging", "packaging.version",
    "rich", "rich.console", "rich.traceback",
    "blinker", "pillow", "PIL", "PIL.Image",
    "cachetools", "platformdirs", "tzdata",
    "watchdog", "watchdog.observers", "watchdog.observers.polling",
    "watchdog.events", "pydeck", "gitdb", "smmap",
    "markdown_it", "mdurl",
    "agents", "agents.ori_ia", "agents.ori_rp", "agents.ori_wb",
    "agents.ai_provider", "core", "core._paths",
    "core.job_runner", "core.dashboard_cache",
    "core.shared_profile",
]

a = Analysis(
    ["run.py"],
    pathex=[str(PROJ)],
    binaries=[],
    datas=added_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "scipy", "sklearn",
        "IPython", "jupyter", "notebook",
        "pytest", "playwright", "greenlet", "peewee",
        "PyQt5", "PyQt6", "wx", "gi",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="Auri",
    debug=False,
    strip=False,
    upx=True,
    upx_exclude=["vcruntime140.dll", "python312.dll", "api-ms-win-*.dll"],
    runtime_tmpdir=None,
    console=True,   # Set False for release; keep True for debugging
    icon=None,      # Set to "assets/auri.ico" when available
)
