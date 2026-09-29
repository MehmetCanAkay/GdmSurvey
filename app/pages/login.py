"""Uzman seçimi ve şifre ile giriş."""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

from app.dependencies import build_services


def render() -> None:
    """Giriş formunu çizer ve başarılı oturumda panele geçer."""
    if "evaluator_id" in st.session_state:
        st.switch_page("pages/dashboard.py")

    st.title("GDM LLM Çalışması")
    st.subheader("Uzman puanlama girişi")
    st.caption("Yanıtlar kör olarak sunulur. Model adı bu uygulamada görünmez.")

    services = build_services()
    evaluators = services.evaluators.list_for_login()
    if not evaluators:
        st.warning("Kayıtlı uzman yok. Önce `python -m src.query_runner --init` çalıştırın.")
        return

    labels = {item["name"]: item["evaluator_id"] for item in evaluators}
    with st.form("login_form"):
        selected = st.selectbox(
            "Uzman",
            options=list(labels),
            index=None,
            placeholder="Uzman seçin",
        )
        password = st.text_input("Şifre", type="password")
        submitted = st.form_submit_button("Giriş yap", type="primary")

    if not submitted:
        return
    if selected is None or not password:
        st.error("Uzman ve şifre zorunludur.")
        return

    result = services.evaluators.authenticate(labels[selected], password)
    if result is None:
        st.error("Şifre hatalı.")
        return

    st.session_state["evaluator_id"] = result["evaluator_id"]
    st.session_state["evaluator_name"] = result["name"]
    st.session_state["evaluator_role"] = result["role"]
    st.switch_page("pages/dashboard.py")


render()
