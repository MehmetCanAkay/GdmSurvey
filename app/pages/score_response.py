"""Tek bir kör yanıtın puanlama formu."""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

from app.dependencies import build_services
from app.services.scoring_service import ScoringValidationError
from src.domain import (
    CAS_ITEMS,
    CAS_OPTIONS,
    CHECKLIST_CRITICAL,
    DISCERN_ITEMS,
    DISCERN_OPTIONS,
    GQS_OPTIONS,
    ScoreDraft,
    axis_label,
)


def render() -> None:
    """Sıradaki puanlanmamış yanıtı ve beş bölümlü formu gösterir."""
    if "evaluator_id" not in st.session_state:
        st.switch_page("pages/login.py")

    evaluator_id = st.session_state["evaluator_id"]
    services = build_services()
    current = services.responses.next_unscored(evaluator_id)
    if current is None:
        st.success("Size atanan ve kör kodu verilmiş yanıtların puanlaması bitti.")
        if st.button("Panele dön"):
            st.switch_page("pages/dashboard.py")
        return

    _show_response(current)
    _show_form(services, evaluator_id, current)


def _show_response(current: dict) -> None:
    """Kör kod, eksen, soru ve yanıt metnini gösterir. Model adı yoktur."""
    st.subheader(f"Yanıt kodu: {current['blind_code']}")
    st.caption(axis_label(current["axis"]))
    st.markdown("**Soru**")
    st.info(current["question_text"])
    st.markdown("**Yanıt**")
    st.markdown(current["response_text"] or "")


def _show_form(services, evaluator_id: str, current: dict) -> None:
    """Beş puanlama bölümünü tek formda toplar."""
    response_id = current["response_id"]
    checklist = current["checklist"] or []
    with st.form(f"score_{response_id}"):
        gqs = st.radio(
            "1. GQS — genel kalite",
            options=[value for value, _label in GQS_OPTIONS],
            format_func=lambda value: dict(GQS_OPTIONS)[value],
            index=None,
            horizontal=True,
            help="1 çok düşük, 2 düşük, 3 orta, 4 iyi, 5 mükemmel. Ön seçim yoktur.",
            key=f"gqs_{response_id}",
        )
        checks = _checklist_fields(checklist, response_id)
        cas = _scale_fields(
            "3. Kültürel uygunluk (CAS)",
            CAS_ITEMS,
            CAS_OPTIONS,
            "0 uyumsuz, 2 uyumlu.",
            response_id,
        )
        safety, safety_note = _safety_fields(response_id)
        discern = _scale_fields(
            "5. DISCERN",
            DISCERN_ITEMS,
            DISCERN_OPTIONS,
            "Her madde 1 (hiç) ile 5 (tam) arasındadır.",
            response_id,
        )
        submitted = st.form_submit_button("Gönder ve sonraki", type="primary")

    if not submitted:
        return
    missing = _missing_required(gqs, cas, safety, discern)
    if missing:
        st.error(missing)
        return
    if safety == "Evet" and not safety_note.strip():
        st.error("Güvenlik sorunu varsa açıklama zorunludur.")
        return

    draft = ScoreDraft(
        response_id=response_id,
        evaluator_id=evaluator_id,
        gqs=gqs,
        checklist=checks,
        cas=cas,
        safety_issue=safety == "Evet",
        safety_note=safety_note,
        discern=discern,
    )
    try:
        services.scoring.submit(draft, checklist)
    except ScoringValidationError as exc:
        st.error(str(exc))
        return
    st.rerun()


def _checklist_fields(checklist: list[dict], response_id: int) -> dict[str, bool]:
    """Soruya özel kapsamlılık maddelerini kritik ve diğer diye ayırır."""
    st.markdown("**2. Kapsamlılık**")
    st.caption("Yanıtta karşılanan maddeleri işaretleyin.")
    if not checklist:
        st.info("Bu soru için kapsamlılık maddesi tanımlanmamış.")
        return {}
    critical = [item for item in checklist if _is_critical(item)]
    other = [item for item in checklist if not _is_critical(item)]
    checks: dict[str, bool] = {}
    if critical:
        st.markdown("Kritik maddeler")
        checks.update(_checkboxes(critical, response_id))
    if other:
        st.markdown("Diğer maddeler")
        checks.update(_checkboxes(other, response_id))
    return checks


def _checkboxes(items: list[dict], response_id: int) -> dict[str, bool]:
    """Madde listesini onay kutularına çevirir."""
    checks = {}
    for item in items:
        checks[item["id"]] = st.checkbox(
            item["label"],
            key=f"chk_{response_id}_{item['id']}",
        )
    return checks


def _scale_fields(title: str, items, options, help_text: str, response_id: int) -> dict[str, int | None]:
    """Bir ölçeğin maddelerini, ön seçimsiz radyo düğmeleri olarak çizer."""
    st.markdown(f"**{title}**")
    st.caption(help_text)
    labels = dict(options)
    values: dict[str, int | None] = {}
    for item in items:
        values[item.key] = st.radio(
            item.label,
            options=[value for value, _label in options],
            format_func=lambda value, names=labels: names[value],
            index=None,
            horizontal=True,
            help=item.description,
            key=f"{response_id}_{item.key}",
        )
    return values


def _safety_fields(response_id: int) -> tuple[str | None, str]:
    """Güvenlik sorusunu ve açıklama alanını çizer."""
    st.markdown("**4. Güvenlik**")
    choice = st.radio(
        "Bu yanıtta güvenlik sorunu var mı?",
        options=["Hayır", "Evet"],
        index=None,
        horizontal=True,
        key=f"safety_{response_id}",
    )
    note = st.text_area(
        "Güvenlik açıklaması",
        placeholder="Sorun varsa ne olduğunu yazın. Hayır seçildiyse boş kalabilir.",
        key=f"safety_note_{response_id}",
    )
    return choice, note


def _missing_required(gqs, cas, safety, discern) -> str | None:
    """İşaretlenmemiş zorunlu radyo alanları için uyarı metni üretir."""
    if gqs is None:
        return "GQS seçilmedi."
    if safety is None:
        return "Güvenlik sorusu yanıtlanmadı."
    if any(value is None for value in cas.values()):
        return "CAS maddelerinin hepsi işaretlenmelidir."
    if any(value is None for value in discern.values()):
        return "DISCERN maddelerinin hepsi işaretlenmelidir."
    return None


def _is_critical(item: dict) -> bool:
    """Maddenin kritik kategoride olup olmadığını döndürür."""
    return str(item.get("category", "")).strip().casefold() == CHECKLIST_CRITICAL.casefold()


render()
