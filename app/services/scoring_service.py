"""Puan formunu doğrular ve kaydeder."""

from sqlalchemy.exc import IntegrityError

from src.database import ScoreRepository
from src.domain import CAS_ITEMS, DISCERN_ITEMS, ScoreDraft


class ScoringValidationError(ValueError):
    """Form kuralları sağlanmadığında fırlatılır."""


class ScoringService:
    """Puan repository'sine yazmadan önce aralık ve zorunlu alan kontrolü yapar."""

    def __init__(self, scores: ScoreRepository):
        """Puan repository'sini dışarıdan alır."""
        self._scores = scores

    def submit(self, draft: ScoreDraft, checklist_items: list[dict]) -> int:
        """
        Geçerli puanı kaydeder ve score_id döndürür.

        checklist_items sorunun kapsamlılık maddeleridir. weight yoksa 1 sayılır.
        """
        expected_checklist_ids = [item["id"] for item in checklist_items]
        self._validate(draft, expected_checklist_ids)
        checklist = {
            item_id: bool(draft.checklist.get(item_id, False))
            for item_id in expected_checklist_ids
        }
        checklist_pct, weighted_pct = checklist_scores(checklist_items, checklist)
        note = None
        if draft.safety_issue and draft.safety_note:
            note = draft.safety_note.strip()
        payload = {
            "response_id": draft.response_id,
            "evaluator_id": draft.evaluator_id,
            "gqs": draft.gqs,
            "checklist": checklist,
            "checklist_pct": checklist_pct,
            "checklist_weighted_pct": weighted_pct,
            "safety_issue": draft.safety_issue,
            "safety_note": note,
        }
        for item in CAS_ITEMS:
            payload[item.key] = draft.cas[item.key]
        for item in DISCERN_ITEMS:
            payload[item.key] = draft.discern[item.key]
        try:
            return self._scores.add(payload)
        except IntegrityError as exc:
            raise ScoringValidationError("Bu yanıtı daha önce puanladınız.") from exc

    def _validate(self, draft: ScoreDraft, expected_checklist_ids: list[str]) -> None:
        """Aralık, eksik madde ve güvenlik notu kurallarını denetler."""
        if draft.gqs not in range(1, 6):
            raise ScoringValidationError("GQS 1 ile 5 arasında olmalıdır.")
        self._require_scale(draft.cas, CAS_ITEMS, 0, 2, "CAS")
        self._require_scale(draft.discern, DISCERN_ITEMS, 1, 5, "DISCERN")
        if draft.safety_issue and not (draft.safety_note or "").strip():
            raise ScoringValidationError("Güvenlik sorunu varsa açıklama zorunludur.")
        unknown = set(draft.checklist) - set(expected_checklist_ids)
        if unknown:
            raise ScoringValidationError("Soru listesinde olmayan kapsamlılık maddesi var.")

    @staticmethod
    def _require_scale(values: dict, items, low: int, high: int, name: str) -> None:
        """Ölçek maddelerinin hepsinin verilen aralıkta olduğunu denetler."""
        for item in items:
            if item.key not in values or values[item.key] is None:
                raise ScoringValidationError(f"{name} maddesi eksik: {item.label}")
            if values[item.key] not in range(low, high + 1):
                raise ScoringValidationError(
                    f"{name} / {item.label} değeri {low} ile {high} arasında olmalıdır."
                )


def checklist_scores(items: list[dict], checked: dict[str, bool]) -> tuple[float | None, float | None]:
    """
    Kapsamlılık yüzdelerini hesaplar: (ağırlıksız, ağırlıklı).

    Madde yoksa ikisi de None döner.
    """
    if not items:
        return None, None
    hits = sum(1 for item in items if checked.get(item["id"]))
    total_weight = sum(_weight(item) for item in items)
    hit_weight = sum(_weight(item) for item in items if checked.get(item["id"]))
    plain = round(100 * hits / len(items), 2)
    weighted = round(100 * hit_weight / total_weight, 2) if total_weight else None
    return plain, weighted


def _weight(item: dict) -> float:
    """Madde ağırlığını okur. Tanımsız veya geçersizse 1 döner."""
    try:
        value = float(item.get("weight", 1))
    except (TypeError, ValueError):
        return 1.0
    return value if value > 0 else 1.0
