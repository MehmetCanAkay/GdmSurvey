"""Uzmanın puanlama ilerlemesini hesaplar."""

from src.database import EvaluatorRepository, ResponseRepository, ScoreRepository
from src.domain import axis_label


class ProgressService:
    """Toplam, atanan, puanlanan ve eksen kırılımını bir araya getirir."""

    def __init__(
        self,
        responses: ResponseRepository,
        scores: ScoreRepository,
        evaluators: EvaluatorRepository,
    ):
        """Yanıt, puan ve uzman repository'lerini dışarıdan alır."""
        self._responses = responses
        self._scores = scores
        self._evaluators = evaluators

    def summary(self, evaluator_id: str) -> dict:
        """Panelde gösterilecek sayıları döndürür."""
        evaluator = self._evaluators.get(evaluator_id)
        if evaluator is None:
            return {
                "total_responses": 0,
                "assigned": 0,
                "ready": 0,
                "scored": 0,
                "remaining": 0,
                "by_axis": [],
            }
        axes = evaluator["assigned_axes"]
        counts = self._responses.axis_counts()
        scored_by_axis = self._scores.scored_counts_by_axis(evaluator_id)
        ready = sum(counts.get(axis, {}).get("ready", 0) for axis in axes)
        scored = sum(scored_by_axis.values())
        return {
            "total_responses": sum(item["total"] for item in counts.values()),
            "assigned": sum(counts.get(axis, {}).get("total", 0) for axis in axes),
            "ready": ready,
            "scored": scored,
            "remaining": max(0, ready - scored),
            "by_axis": [
                {
                    "axis": axis,
                    "label": axis_label(axis),
                    "assigned": counts.get(axis, {}).get("total", 0),
                    "scored": scored_by_axis.get(axis, 0),
                }
                for axis in axes
            ],
        }
