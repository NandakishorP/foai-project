"""Truth for Sale — review-day dashboard (DECISIONS D-062).

Run from the repository root:  make dashboard   (or: streamlit run dashboard/app.py)

Works offline: every view reads precomputed results (see dashboard/views.py). If Streamlit
fails on the review machine, the same key figures are PNGs in dashboard/fallback/.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import views  # noqa: E402

views.PAGES.update({
    views.landing: st.Page(views.landing, title="Demo walkthrough", icon=":material/play_circle:", default=True),
    views.act1: st.Page(views.act1, title="Act 1 · The market works", url_path="market"),
    views.act2: st.Page(views.act2, title="Act 2 · Predators", url_path="predators"),
    views.act3: st.Page(views.act3, title="Act 3 · The defense", url_path="defense"),
    views.act4: st.Page(views.act4, title="Act 4 · Search", url_path="search"),
    views.verdicts: st.Page(views.verdicts, title="Verdicts and the whale", url_path="verdicts"),
})

st.set_page_config(page_title="Truth for Sale", layout="wide")
st.navigation(list(views.PAGES.values())).run()
