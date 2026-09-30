"""Uzman seçimi ve şifre ile giriş."""

import sys
from pathlib import Path

def _ensure_project_root() -> None:
    """Repo kökünü import yoluna ekler. Üst dizin sayısı sabit değildir."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "src" / "database.py").is_file() and (parent / "app" / "dependencies.py").is_file():
            root = str(parent)
            if root not in sys.path:
                sys.path.insert(0, root)
            return


_ensure_project_root()

import streamlit as st

from app.dependencies import app_services
from app.study_info import render_study_info


@st.cache_data(ttl=600, show_spinner=False)
def _login_choices() -> list[dict]:
    """Giriş listesini önbellekten verir; her yeniden çizimde veritabanına gidilmez."""
    return app_services().evaluators.list_for_login()


def render() -> None:
    """Giriş formunu çizer ve başarılı oturumda panele geçer."""
    if "evaluator_id" in st.session_state:
        st.switch_page("pages/dashboard.py")

    st.title("GDM LLM Çalışması")
    st.subheader("Uzman puanlama girişi")
    render_study_info(expanded=True)

    services = app_services()
    with st.spinner("Yükleniyor..."):
        evaluators = _login_choices()
    if not evaluators:
        _login_choices.clear()
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

    with st.spinner("Giriş yapılıyor..."):
        result = services.evaluators.authenticate(labels[selected], password)
    if result is None:
        st.error("Şifre hatalı.")
        return

    st.session_state["evaluator_id"] = result["evaluator_id"]
    st.session_state["evaluator_name"] = result["name"]
    st.session_state["evaluator_role"] = result["role"]
    st.switch_page("pages/dashboard.py")


render()
