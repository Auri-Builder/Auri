"""
Home.py — Auri navigation host
-------------------------------
Entry point. Defines all pages via st.navigation() and runs the current page.
Hub content lives in pages/hub.py.
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="Auri — Financial Intelligence",
    layout="wide",
    initial_sidebar_state="auto",
)

pg = st.navigation(
    {
        "Hub": [
            st.Page("pages/hub.py",             title="Auri Hub",          icon=":material/home:",           url_path="",              default=True),
        ],
        "Agents": [
            st.Page("pages/1_Portfolio.py",     title="Portfolio",         icon=":material/show_chart:",     url_path="portfolio"),
            st.Page("pages/6_WealthBuilder.py", title="Wealth Builder",    icon=":material/savings:",        url_path="wealthbuilder"),
            st.Page("pages/7_Retirement.py",    title="Retirement Planner",icon=":material/elderly:",        url_path="retirement"),
        ],
        "Tools": [
            st.Page("pages/wizard.py",          title="Setup Wizard",      icon=":material/settings:",       url_path="wizard"),
            st.Page("pages/5_Analysis.py",      title="Analysis",          icon=":material/analytics:",      url_path="analysis"),
            st.Page("pages/profile.py",         title="Investor Profile",  icon=":material/person:",         url_path="profile"),
            st.Page("pages/snapshots.py",       title="Snapshots",         icon=":material/photo_camera:",   url_path="snapshots"),
            st.Page("pages/health.py",          title="Health Check",      icon=":material/health_and_safety:", url_path="health"),
        ],
    }
)
pg.run()
