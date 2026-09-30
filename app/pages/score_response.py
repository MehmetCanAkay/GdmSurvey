"""Tek bir kör yanıtın puanlama formu."""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

from app.dependencies import app_services
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
    """Sıradaki puanlanmamış yanıtı veya düzeltme formunu gösterir."""
    if "evaluator_id" not in st.session_state:
        st.switch_page("pages/login.py")

    evaluator_id = st.session_state["evaluator_id"]
    services = app_services()
    edit_id = st.session_state.get("edit_response_id")
    if edit_id is not None:
        _render_edit(services, evaluator_id, int(edit_id))
        return

    with st.spinner("Yanıt yükleniyor..."):
        current = services.responses.next_unscored(evaluator_id)
    if current is None:
        st.success("Size atanan ve kör kodu verilmiş yanıtların puanlaması bitti.")
        if st.button("Panele dön"):
            st.switch_page("pages/dashboard.py")
        return

    _show_response(current)
    _show_form(services, evaluator_id, current, initial=None)


def _render_edit(services, evaluator_id: str, response_id: int) -> None:
    """Kayıtlı puanla dolu düzeltme formunu çizer."""
    with st.spinner("Yanıt yükleniyor..."):
        pair = services.responses.scored_for_edit(evaluator_id, response_id)
    if pair is None:
        st.error("Bu yanıt düzeltmeye açık değil.")
        if st.button("Panele dön"):
            _leave_edit()
            st.switch_page("pages/dashboard.py")
        return
    current, score = pair
    st.caption("Düzeltme")
    _show_response(current)
    _prepare_edit_widgets(response_id, current.get("checklist") or [])
    _show_form(services, evaluator_id, current, initial=score)


def _show_response(current: dict) -> None:
    """Kör kod, eksen, soru ve yanıt metnini gösterir. Model adı yoktur."""
    st.subheader(f"Yanıt kodu: {current['blind_code']}")
    st.caption(axis_label(current["axis"]))
    st.markdown("**Soru**")
    st.info(current["question_text"])
    st.markdown("**Yanıt**")
    st.markdown(current["response_text"] or "")


def _show_form(services, evaluator_id: str, current: dict, initial: dict | None) -> None:
    """Beş puanlama bölümünü tek formda toplar. initial doluysa düzeltme kipidir."""
    editing = initial is not None
    response_id = current["response_id"]
    checklist = current["checklist"] or []
    prefix = "edit_" if editing else ""
    saved_checks = (initial or {}).get("checklist") or {}
    gqs_key = f"{prefix}gqs_{response_id}"
    gqs_index = None
    if gqs_key not in st.session_state:
        gqs_index = _index_of(GQS_OPTIONS, None if initial is None else initial.get("gqs"))
    with st.form(f"{prefix}score_{response_id}"):
        gqs = st.radio(
            "1. GQS — genel kalite",
            options=[value for value, _label in GQS_OPTIONS],
            format_func=lambda value: dict(GQS_OPTIONS)[value],
            index=gqs_index,
            horizontal=True,
            help=(
                "Kayıtlı puan seçili gelir; değiştirebilirsiniz."
                if editing
                else "1 çok düşük, 2 düşük, 3 orta, 4 iyi, 5 mükemmel. Ön seçim yoktur."
            ),
            key=gqs_key,
        )
        checks = _checklist_fields(
            checklist,
            response_id,
            prefix,
            saved_checks if editing else None,
        )
        cas = _scale_fields(
            "3. Kültürel uygunluk (CAS)",
            CAS_ITEMS,
            CAS_OPTIONS,
            "0 uyumsuz, 2 uyumlu.",
            response_id,
            prefix,
            None if initial is None else initial.get("cas"),
        )
        safety, safety_note = _safety_fields(response_id, prefix, initial)
        discern = _scale_fields(
            "5. DISCERN",
            DISCERN_ITEMS,
            DISCERN_OPTIONS,
            "Her madde 1 (hiç) ile 5 (tam) arasındadır.",
            response_id,
            prefix,
            None if initial is None else initial.get("discern"),
        )
        if editing:
            submitted = st.form_submit_button("Düzeltmeyi kaydet", type="primary")
            cancel = st.form_submit_button("Vazgeç")
        else:
            submitted = st.form_submit_button("Gönder ve sonraki", type="primary")
            cancel = False

    if cancel:
        _leave_edit()
        st.switch_page("pages/dashboard.py")
        return
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
        with st.spinner("Kaydediliyor..."):
            if editing:
                services.scoring.update(draft, checklist)
            else:
                services.scoring.submit(draft, checklist)
    except ScoringValidationError as exc:
        st.error(str(exc))
        return
    if editing:
        _leave_edit()
        st.toast("Puan güncellendi.")
        st.switch_page("pages/dashboard.py")
        return
    st.rerun()


def _checklist_fields(
    checklist: list[dict],
    response_id: int,
    prefix: str,
    initial_checks: dict | None,
) -> dict[str, bool]:
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
        checks.update(_checkboxes(critical, response_id, prefix, initial_checks))
    if other:
        st.markdown("Diğer maddeler")
        checks.update(_checkboxes(other, response_id, prefix, initial_checks))
    return checks


def _checkboxes(
    items: list[dict],
    response_id: int,
    prefix: str,
    initial_checks: dict | None,
) -> dict[str, bool]:
    """Madde listesini onay kutularına çevirir."""
    checks = {}
    for item in items:
        key = f"{prefix}chk_{response_id}_{item['id']}"
        extras = {}
        if initial_checks is not None and key not in st.session_state:
            extras["value"] = bool(initial_checks.get(item["id"]))
        checks[item["id"]] = st.checkbox(item["label"], key=key, **extras)
    return checks


def _scale_fields(
    title: str,
    items,
    options,
    help_text: str,
    response_id: int,
    prefix: str,
    initial_values: dict | None,
) -> dict[str, int | None]:
    """Bir ölçeğin maddelerini radyo düğmeleri olarak çizer."""
    st.markdown(f"**{title}**")
    st.caption(help_text)
    labels = dict(options)
    values: dict[str, int | None] = {}
    for item in items:
        key = f"{prefix}{response_id}_{item.key}"
        selected = None if initial_values is None else initial_values.get(item.key)
        if key in st.session_state:
            index = None
        else:
            index = _index_of(options, selected)
        values[item.key] = st.radio(
            item.label,
            options=[value for value, _label in options],
            format_func=lambda value, names=labels: names[value],
            index=index,
            horizontal=True,
            help=item.description,
            key=key,
        )
    return values


def _safety_fields(response_id: int, prefix: str, initial: dict | None) -> tuple[str | None, str]:
    """Güvenlik sorusunu ve açıklama alanını çizer."""
    st.markdown("**4. Güvenlik**")
    options = ["Hayır", "Evet"]
    choice_key = f"{prefix}safety_{response_id}"
    note_key = f"{prefix}safety_note_{response_id}"
    if choice_key in st.session_state or initial is None:
        choice_index = None
    else:
        choice_index = options.index("Evet" if initial.get("safety_issue") else "Hayır")
    choice = st.radio(
        "Bu yanıtta güvenlik sorunu var mı?",
        options=options,
        index=choice_index,
        horizontal=True,
        key=choice_key,
    )
    extras = {}
    if initial is not None and note_key not in st.session_state:
        extras["value"] = initial.get("safety_note") or ""
    note = st.text_area(
        "Güvenlik açıklaması",
        placeholder="Sorun varsa ne olduğunu yazın. Hayır seçildiyse boş kalabilir.",
        key=note_key,
        **extras,
    )
    return choice, note


def _prepare_edit_widgets(response_id: int, checklist: list[dict]) -> None:
    """Düzeltme formuna ilk girişte eski widget durumunu siler ki kayıtlı puan görünsün."""
    if st.session_state.get("_edit_form_for") == response_id:
        return
    keys = [
        f"edit_gqs_{response_id}",
        f"edit_safety_{response_id}",
        f"edit_safety_note_{response_id}",
    ]
    for item in (*CAS_ITEMS, *DISCERN_ITEMS):
        keys.append(f"edit_{response_id}_{item.key}")
    for item in checklist:
        keys.append(f"edit_chk_{response_id}_{item['id']}")
    for key in keys:
        st.session_state.pop(key, None)
    st.session_state["_edit_form_for"] = response_id


def _leave_edit() -> None:
    """Düzeltme oturumunu kapatır."""
    st.session_state.pop("edit_response_id", None)
    st.session_state.pop("_edit_form_for", None)


def _index_of(options, selected) -> int | None:
    """Seçili değerin sıra numarasını döndürür. Değer yoksa ön seçim olmaz."""
    values = [value for value, _label in options]
    if selected not in values:
        return None
    return values.index(selected)


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
