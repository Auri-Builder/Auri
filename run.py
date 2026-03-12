"""
run.py — Auri launcher
-----------------------
Entry point for both:
  - PyInstaller --onefile exe (frozen mode)
  - Direct dev launch: python run.py

Starts Streamlit server and opens browser automatically.
NOT needed for normal dev — use: streamlit run Home.py
"""
from __future__ import annotations

import os
import sys
import time
import threading
import webbrowser
from pathlib import Path


def _setup() -> Path:
    """Set sys.path and return the directory containing Home.py."""
    if getattr(sys, "frozen", False):
        bundle = Path(sys._MEIPASS)  # type: ignore[attr-defined]
        if str(bundle) not in sys.path:
            sys.path.insert(0, str(bundle))
        # Ensure writable data dirs exist next to the exe
        _appdata = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
        data_root = Path(_appdata) / "Auri" / "data"
        for sub in ["portfolio", "wealth", "retirement", "retirement/scenarios", "derived"]:
            (data_root / sub).mkdir(parents=True, exist_ok=True)
        return bundle
    else:
        here = Path(__file__).resolve().parent
        if str(here) not in sys.path:
            sys.path.insert(0, str(here))
        return here


def _silence_streamlit_startup() -> None:
    """Write ~/.streamlit/config.toml to suppress first-run prompts."""
    cfg_dir = Path.home() / ".streamlit"
    cfg_dir.mkdir(exist_ok=True)
    cfg_file = cfg_dir / "config.toml"
    if not cfg_file.exists():
        cfg_file.write_text(
            '[general]\nemail = ""\n\n'
            '[browser]\ngatherUsageStats = false\n\n'
            '[server]\nheadless = true\nport = 8501\n'
            'enableCORS = false\nenableXsrfProtection = false\n',
            encoding="utf-8",
        )


def _patch_importlib_metadata() -> None:
    """
    Patch importlib.metadata.version() so missing dist-info in a frozen
    bundle returns '0.0.0' instead of raising PackageNotFoundError.
    Streamlit calls importlib.metadata.version('streamlit') at import time.
    """
    import importlib.metadata as _ilm
    _orig = _ilm.version

    def _safe_version(pkg: str) -> str:
        try:
            return _orig(pkg)
        except _ilm.PackageNotFoundError:
            return "0.0.0"

    _ilm.version = _safe_version  # type: ignore[assignment]


def main() -> None:
    app_dir = _setup()
    _silence_streamlit_startup()

    # Patch metadata lookup before importing streamlit (frozen bundles lack dist-info)
    if getattr(sys, "frozen", False):
        _patch_importlib_metadata()

    port = 8501
    url = f"http://localhost:{port}"

    # Open browser after a delay (server needs a few seconds to start)
    def _open():
        time.sleep(4)
        webbrowser.open(url)

    threading.Thread(target=_open, daemon=True).start()

    # Use bootstrap.run() directly — works in frozen mode unlike the CLI
    from streamlit.web import bootstrap
    from streamlit import config as _st_cfg

    _st_cfg.set_option("server.headless", True)
    _st_cfg.set_option("server.port", port)
    _st_cfg.set_option("browser.gatherUsageStats", False)
    _st_cfg.set_option("server.enableCORS", False)
    _st_cfg.set_option("server.enableXsrfProtection", False)
    _st_cfg.set_option("server.fileWatcherType", "none")

    bootstrap.run(
        main_script_path=str(app_dir / "Home.py"),
        is_hello=False,
        args=[],
        flag_options={},
    )


if __name__ == "__main__":
    main()
