"""
GDM kör puanlama arayüzü.

Giriş yapılmadan yalnızca giriş sayfası görünür.
Model adı hiçbir sayfada gösterilmez.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st


def apply_streamlit_secrets() -> None:
    """Streamlit Cloud üzerindeki DATABASE_URL değerini ortama taşır."""
    try:
        if "DATABASE_URL" in st.secrets:
            os.environ["DATABASE_URL"] = st.secrets["DATABASE_URL"]
    except Exception:
        return


apply_streamlit_secrets()

st.set_page_config(page_title="GDM Puanlama", page_icon="📋", layout="wide")

# Üç sayfa her zaman kayıtlıdır; böylece switch_page her yönde çalışır ve
# çıkışta "sayfa bulunamadı" uyarısı çıkmaz. Hazır menü gizlenir, yerine
# yalnızca oturum açıkken görünen menü çizilir.
logged_in = "evaluator_id" in st.session_state
login_page = st.Page("pages/login.py", title="Giriş", default=not logged_in)
dashboard_page = st.Page("pages/dashboard.py", title="Panel", default=logged_in)
score_page = st.Page("pages/score_response.py", title="Puanlama")

navigation = st.navigation([login_page, dashboard_page, score_page], position="hidden")

if logged_in:
    with st.sidebar:
        st.page_link(dashboard_page, label="Panel")
        st.page_link(score_page, label="Puanlama")

navigation.run()
