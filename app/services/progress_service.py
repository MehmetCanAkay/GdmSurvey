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
        assigned_by_axis = self._responses.count_by_axis()
        scored_by_axis = self._scores.scored_counts_by_axis(evaluator_id)
        ready = len(self._responses.list_blinded_for_axes(axes))
        scored = self._scores.count_for_evaluator(evaluator_id)
        return {
            "total_responses": self._responses.count(),
            "assigned": self._responses.count_for_axes(axes),
            "ready": ready,
            "scored": scored,
            "remaining": max(0, ready - scored),
            "by_axis": [
                {
                    "axis": axis,
                    "label": axis_label(axis),
                    "assigned": assigned_by_axis.get(axis, 0),
                    "scored": scored_by_axis.get(axis, 0),
                }
                for axis in axes
            ],
        }
