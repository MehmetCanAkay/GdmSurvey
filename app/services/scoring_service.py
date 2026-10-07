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

    def submit(self, draft: ScoreDraft, checklist_items: list[dict], cas_items: list[str]) -> int:
        """
        Geçerli puanı kaydeder ve score_id döndürür.

        checklist_items sorunun kapsamlılık maddeleridir. weight yoksa 1 sayılır.
        cas_items sorunun puanlanan CAS anahtarlarıdır; diğer CAS maddeleri boş kaydedilir.
        """
        try:
            return self._scores.add(self._build_payload(draft, checklist_items, cas_items))
        except IntegrityError as exc:
            raise ScoringValidationError("Bu yanıtı daha önce puanladınız.") from exc

    def update(self, draft: ScoreDraft, checklist_items: list[dict], cas_items: list[str]) -> None:
        """Mevcut puanın üzerine yazar. Kayıt yoksa hata fırlatır."""
        payload = self._build_payload(draft, checklist_items, cas_items)
        if not self._scores.update(payload):
            raise ScoringValidationError("Düzeltilecek puan bulunamadı.")

    def _build_payload(
        self,
        draft: ScoreDraft,
        checklist_items: list[dict],
        cas_items: list[str],
    ) -> dict:
        """Doğrulanmış puanı repository'nin beklediği sözlüğe çevirir."""
        expected_checklist_ids = [item["id"] for item in checklist_items]
        applicable_cas = applicable_cas_items(cas_items)
        self._validate(draft, expected_checklist_ids, applicable_cas)
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
        applicable_keys = {item.key for item in applicable_cas}
        for item in CAS_ITEMS:
            payload[item.key] = draft.cas[item.key] if item.key in applicable_keys else None
        for item in DISCERN_ITEMS:
            payload[item.key] = draft.discern[item.key]
        return payload

    def _validate(self, draft: ScoreDraft, expected_checklist_ids: list[str], applicable_cas) -> None:
        """Aralık, eksik madde, soru dışı CAS maddesi ve güvenlik notu kurallarını denetler."""
        if draft.gqs not in range(1, 6):
            raise ScoringValidationError("GQS 1 ile 5 arasında olmalıdır.")
        self._require_scale(draft.cas, applicable_cas, 0, 2, "CAS")
        applicable_keys = {item.key for item in applicable_cas}
        extra_cas = [
            key for key, value in draft.cas.items()
            if key not in applicable_keys and value is not None
        ]
        if extra_cas:
            raise ScoringValidationError("Bu soruda puanlanmayan bir CAS maddesine değer girilmiş.")
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


def applicable_cas_items(cas_items: list[str]) -> tuple:
    """
    Sorunun CAS anahtarlarını CAS_ITEMS sırasındaki madde tanımlarına çevirir.

    Boş liste veya bilinmeyen anahtar, eksik CAS ile puan kaydedilmesin diye hata sayılır.
    """
    known = {item.key for item in CAS_ITEMS}
    if not cas_items or any(key not in known for key in cas_items):
        raise ScoringValidationError("Bu sorunun CAS madde listesi tanımsız.")
    return tuple(item for item in CAS_ITEMS if item.key in cas_items)


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
