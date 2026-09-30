"""Uzmanın puanlama özeti."""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st

from app.dependencies import app_services
from app.study_info import render_study_info


def render() -> None:
    """Atanan, puanlanan ve kalan yanıt sayılarını gösterir."""
    if "evaluator_id" not in st.session_state:
        st.switch_page("pages/login.py")

    evaluator_id = st.session_state["evaluator_id"]
    # Panele dönüş düzeltme niyetini kapatır. "Düzelt" aynı turda anahtarı yeniden yazar.
    st.session_state.pop("edit_response_id", None)
    st.session_state.pop("_edit_form_for", None)

    left, right = st.columns([4, 1])
    with left:
        st.title("Puanlama paneli")
        st.markdown(
            f"**{st.session_state.get('evaluator_name', '')}** "
            f"({st.session_state.get('evaluator_role', '')})"
        )
    with right:
        if st.button("Çıkış"):
            _logout()
    render_study_info(expanded=False)

    with st.spinner("İlerleme bilgisi yükleniyor..."):
        progress = app_services().progress.summary(evaluator_id)

    total_col, assigned_col, scored_col, remaining_col = st.columns(4)
    total_col.metric("Tüm yanıtlar", progress["total_responses"])
    assigned_col.metric("Size atanan", progress["assigned"])
    scored_col.metric("Puanlanan", progress["scored"])
    remaining_col.metric("Kalan", progress["remaining"])

    if progress["assigned"] > 0:
        st.progress(
            min(progress["scored"] / progress["assigned"], 1.0),
            text=f"{progress['scored']} / {progress['assigned']} atanan yanıt puanlandı",
        )

    if progress["assigned"] > progress["ready"]:
        st.info(
            "Kör kodu henüz atanmamış yanıtlar puanlamaya kapalıdır. "
            "Kodlar araştırmacı tarafından toplu verilir."
        )

    if progress["by_axis"]:
        st.subheader("Eksen kırılımı")
        table = pd.DataFrame(progress["by_axis"])
        st.dataframe(
            table.rename(
                columns={
                    "label": "Eksen",
                    "assigned": "Atanan",
                    "scored": "Puanlanan",
                }
            )[["Eksen", "Atanan", "Puanlanan"]],
            hide_index=True,
            width="stretch",
        )

    if progress["remaining"] == 0:
        st.success("Şu an puanlanacak açık yanıt yok.")
    if progress["scored"] > 0:
        _scored_editor(evaluator_id)
    if st.button("Puanlamaya devam et", type="primary"):
        st.switch_page("pages/score_response.py")


def _scored_editor(evaluator_id: str) -> None:
    """Puanlanmış yanıtları kör kodla listeler ve düzeltme sayfasına geçirir."""
    st.subheader("Puanladıklarım")
    st.caption("Düzeltme, önceki puanın üzerine yazılır.")
    scored = app_services().responses.list_scored(evaluator_id)
    if not scored:
        return
    options = [
        f"{item['blind_code']} — {item['label']} — GQS {item['gqs']}"
        for item in scored
    ]
    selected = st.selectbox(
        "Düzeltilecek yanıt",
        options=options,
        index=None,
        placeholder="Kör kod seçin",
    )
    if st.button("Düzelt", disabled=selected is None):
        chosen = scored[options.index(selected)]
        st.session_state["edit_response_id"] = chosen["response_id"]
        st.switch_page("pages/score_response.py")


def _logout() -> None:
    """Oturum bilgilerini siler ve giriş sayfasına döner."""
    for key in (
        "evaluator_id",
        "evaluator_name",
        "evaluator_role",
        "edit_response_id",
        "_edit_form_for",
    ):
        st.session_state.pop(key, None)
    st.switch_page("pages/login.py")


render()
