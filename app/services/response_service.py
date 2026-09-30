"""Uzmana sıradaki kör yanıtı seçer."""

import random

from src.database import EvaluatorRepository, ResponseRepository, ScoreRepository
from src.domain import axis_label


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
        blinded_ids = self._responses.blinded_ids_for_axes(evaluator["assigned_axes"])
        scored = self._scores.scored_response_ids(evaluator_id)
        for response_id in stable_order(blinded_ids, evaluator_id):
            if response_id not in scored:
                return self._responses.get_blinded(response_id)
        return None

    def list_scored(self, evaluator_id: str) -> list[dict]:
        """Puanlanmış yanıtları kör kod ve eksen etiketiyle döndürür."""
        return [
            {**item, "label": axis_label(item["axis"])}
            for item in self._scores.list_scored_for_evaluator(evaluator_id)
        ]

    def scored_for_edit(self, evaluator_id: str, response_id: int) -> tuple[dict, dict] | None:
        """
        Düzeltmeye açık yanıtı ve mevcut puanı döndürür.

        Yanıt uzmanın ekseninde değilse, kör kodu yoksa veya bu uzman
        puanlamamışsa None döner.
        """
        evaluator = self._evaluators.get(evaluator_id)
        if evaluator is None:
            return None
        current = self._responses.get_blinded(response_id)
        if current is None or current["axis"] not in evaluator["assigned_axes"]:
            return None
        score = self._scores.get_for_evaluator(response_id, evaluator_id)
        if score is None:
            return None
        return current, score


def stable_order(response_ids: list[int], evaluator_id: str) -> list[int]:
    """Yanıt kimliklerini uzman başına sabit bir sıraya dizer."""
    ordered = sorted(response_ids)
    random.Random(evaluator_id).shuffle(ordered)
    return ordered
