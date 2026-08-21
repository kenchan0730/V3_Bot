"""Streamlit entry point. Wires dashboard, home and about into one app."""

import streamlit as st

st.set_page_config(page_title="V4.5 儀表板", page_icon="📊", layout="wide")

PAGES = [
    st.Page("dashboard.py", title="儀表板", icon="📊", default=True),
    st.Page("home.py", title="首頁", icon="🏠"),
    st.Page("about.py", title="關於", icon="ℹ️"),
]

if hasattr(st, "navigation"):
    st.navigation(PAGES).run()
else:  # Streamlit < 1.36 fallback
    import dashboard  # noqa: F401
