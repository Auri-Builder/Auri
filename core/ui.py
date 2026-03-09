"""
core/ui.py — Shared Streamlit UI helpers.
"""
from __future__ import annotations
import streamlit as st


def hide_sidebar_nav() -> None:
    """
    Hide the auto-generated page list from the sidebar.
    Navigation is handled by hub cards and breadcrumbs instead.
    The sidebar itself remains available for widgets.
    """
    st.markdown(
        """
        <style>
        [data-testid="stSidebarNav"] {display: none;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def breadcrumb(pages: list[tuple[str, str | None]]) -> None:
    """
    Render a breadcrumb trail.

    pages: list of (label, page_path) tuples.
           Set page_path=None for the current (bold) page.
    """
    parts = [
        f"**{label}**" if path is None else f"[{label}]({path})"
        for label, path in pages
    ]
    st.caption("  ›  ".join(parts))
