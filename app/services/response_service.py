"""Uzmana sıradaki kör yanıtı seçer."""

import random

from src.database import EvaluatorRepository, ResponseRepository, ScoreRepository


class ResponseService:
    """Eksen süzgeci ve sabit karıştırma sırası burada kurulur."""

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

    def next_unscored(self, evaluator_id: str) -> dict | None:
        """
        Uzmanın puanlamadığı ilk yanıtı döndürür.

        Sıra, uzman kimliğinden türetilen sabit bir karıştırmadır.
        Sayfa yenilense de aynı yanıt gelir. Model bilgisi yoktur.
        """
        evaluator = self._evaluators.get(evaluator_id)
        if evaluator is None:
            return None
        blinded = self._responses.list_blinded_for_axes(evaluator["assigned_axes"])
        scored = self._scores.scored_response_ids(evaluator_id)
        for item in stable_order(blinded, evaluator_id):
            if item["response_id"] not in scored:
                return item
        return None


def stable_order(items: list[dict], evaluator_id: str) -> list[dict]:
    """Yanıtları uzman başına sabit bir sıraya dizer."""
    ordered = sorted(items, key=lambda item: item["response_id"])
    random.Random(evaluator_id).shuffle(ordered)
    return ordered
