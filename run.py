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
        # Resolve Auri home
        _appdata = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
        auri_base = Path(_appdata) / "Auri"
        auri_base.mkdir(parents=True, exist_ok=True)

        import shutil

        # ── One-time migration: flat data/ layout → profiles/default/data/ ──
        old_data = auri_base / "data"
        profiles_dir = auri_base / "profiles"
        default_profile_data = profiles_dir / "default" / "data"
        if old_data.exists() and not profiles_dir.exists():
            # Move the entire old data tree into the default profile
            default_profile_data.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_data), str(default_profile_data))

        # ── Ensure default profile dirs exist ────────────────────────────────
        for sub in ["portfolio", "wealth", "retirement", "retirement/scenarios", "derived"]:
            (default_profile_data / sub).mkdir(parents=True, exist_ok=True)

        # ── Copy static bundled files into default profile if missing ────────
        _static = [
            ("data/portfolio/questions.yaml", default_profile_data / "portfolio" / "questions.yaml"),
        ]
        for _src_rel, _dst in _static:
            if not _dst.exists():
                _src = bundle / _src_rel
                if _src.exists():
                    shutil.copy2(_src, _dst)

        return bundle
    else:
        here = Path(__file__).resolve().parent
        if str(here) not in sys.path:
            sys.path.insert(0, str(here))
        return here


def _silence_streamlit_startup() -> None:
    """Write ~/.streamlit/config.toml to suppress first-run prompts.

    Always overwrite in frozen mode so stale files on the target machine
    can't reintroduce settings (like port = 8501) that trigger Streamlit's
    developmentMode conflict check.  Note: no explicit port entry — 8501 is
    the default and ANY explicit port value raises RuntimeError when
    developmentMode is True.
    """
    cfg_dir = Path.home() / ".streamlit"
    cfg_dir.mkdir(exist_ok=True)
    cfg_file = cfg_dir / "config.toml"
    frozen = getattr(__import__("sys"), "frozen", False)
    if frozen or not cfg_file.exists():
        cfg_file.write_text(
            '[global]\ndevelopmentMode = false\n\n'
            '[general]\nemail = ""\n\n'
            '[browser]\ngatherUsageStats = false\n\n'
            '[server]\nheadless = true\n'
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

    port = 8501

    # Set all config via env vars BEFORE streamlit is imported.
    # set_option("server.port") raises RuntimeError when developmentMode is True,
    # and in a frozen bundle streamlit detects dev-mode through means that survive
    # the env var override.  Env vars are consumed during Streamlit's module init
    # before any conflict validation runs.
    os.environ["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"] = "false"
    os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
    # Do NOT set STREAMLIT_SERVER_PORT — any explicit port value (even 8501)
    # triggers the developmentMode conflict check.  8501 is the default.
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    os.environ["STREAMLIT_SERVER_ENABLE_CORS"] = "false"
    os.environ["STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION"] = "false"
    os.environ["STREAMLIT_SERVER_FILE_WATCHER_TYPE"] = "none"

    # Patch metadata lookup before importing streamlit (frozen bundles lack dist-info)
    if getattr(sys, "frozen", False):
        _patch_importlib_metadata()

    url = f"http://localhost:{port}"

    # Open browser after a delay (server needs a few seconds to start)
    def _open():
        time.sleep(4)
        webbrowser.open(url)

    threading.Thread(target=_open, daemon=True).start()

    # Use bootstrap.run() directly — works in frozen mode unlike the CLI
    from streamlit.web import bootstrap

    bootstrap.run(
        main_script_path=str(app_dir / "Home.py"),
        is_hello=False,
        args=[],
        flag_options={},
    )


if __name__ == "__main__":
    main()
