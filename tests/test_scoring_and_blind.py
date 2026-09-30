"""Puan doğrulaması, tekil kısıt ve kör yanıt sözleşmesi."""

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.services.progress_service import ProgressService
from app.services.response_service import ResponseService
from app.services.scoring_service import ScoringService, ScoringValidationError
from src.database import (
    Base,
    EvaluatorRepository,
    ModelRepository,
    QuestionRepository,
    ResponseRepository,
    Score,
    ScoreRepository,
)
from src.domain import BLINDED_RESPONSE_KEYS, CAS_ITEMS, DISCERN_ITEMS, ScoreDraft, default_evaluators


class StudyRepositoryTests(unittest.TestCase):
    """Geçici SQLite üzerinde şema kurallarını denetler."""

    def setUp(self) -> None:
        """Boş bir veritabanı ve dört uzman kurar."""
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        self.path = Path(handle.name)
        engine = create_engine(f"sqlite:///{self.path}")
        Base.metadata.create_all(engine)
        self.factory = sessionmaker(bind=engine)
        question_file = _question_file()
        try:
            QuestionRepository(self.factory).upsert_from_json(question_file)
        finally:
            question_file.unlink(missing_ok=True)
        ModelRepository(self.factory).upsert_many(
            [
                {
                    "model_id": "M1",
                    "provider": "OpenAI",
                    "model_string": "gpt-test",
                    "temperature": None,
                    "reasoning_effort": "medium",
                    "system_prompt": None,
                }
            ]
        )
        EvaluatorRepository(self.factory).seed_defaults(default_evaluators())

    def tearDown(self) -> None:
        """Geçici veritabanı dosyasını siler."""
        self.path.unlink(missing_ok=True)

    def test_duplicate_response_and_score_are_rejected(self) -> None:
        """Aynı soru-model-tekrar ve aynı uzman-yanıt çifti ikinci kez yazılamaz."""
        responses = ResponseRepository(self.factory)
        responses.add("Q1", "M1", 1, "Yanıt metni.", 10, 20, "gpt-test")
        with self.assertRaises(IntegrityError):
            responses.add("Q1", "M1", 1, "İkinci.", 10, 20, "gpt-test")
        responses.assign_blind_codes(seed=7, expected_count=1)
        ScoringService(ScoreRepository(self.factory)).submit(_draft(1), [])
        with self.assertRaises(ScoringValidationError):
            ScoringService(ScoreRepository(self.factory)).submit(_draft(1), [])

    def test_weighted_checklist_is_stored(self) -> None:
        """Kritik madde (3) işaretli, diğer madde (1) boş: ağırlıksız %50, ağırlıklı %75."""
        responses = ResponseRepository(self.factory)
        responses.add("Q1", "M1", 1, "Yanıt metni.", 10, 20, "gpt-test")
        items = [
            {"id": "a", "label": "Kritik", "category": "Kritik", "weight": 3},
            {"id": "b", "label": "Ek", "category": "Ek", "weight": 1},
        ]
        base = _draft(1)
        draft = ScoreDraft(
            response_id=1,
            evaluator_id="E1",
            gqs=base.gqs,
            checklist={"a": True, "b": False},
            cas=base.cas,
            safety_issue=False,
            safety_note=None,
            discern=base.discern,
        )
        ScoringService(ScoreRepository(self.factory)).submit(draft, items)
        session = self.factory()
        try:
            score = session.query(Score).one()
            self.assertEqual(score.checklist_pct, 50.0)
            self.assertEqual(score.checklist_weighted_pct, 75.0)
        finally:
            session.close()

    def test_blinded_payload_hides_model_and_order_is_stable(self) -> None:
        """Uzmana giden sözlükte model yoktur; sıra yenilemede değişmez."""
        responses = ResponseRepository(self.factory)
        for question_id in ("Q1", "Q2", "Q3", "K1"):
            responses.add(question_id, "M1", 1, f"Metin {question_id}", 1, 1, "gpt-test")
        responses.assign_blind_codes(seed=3, expected_count=4)
        blinded = responses.list_blinded_for_axes(["mutfak", "oruc"])
        self.assertEqual({item["axis"] for item in blinded}, {"mutfak", "oruc"})
        self.assertEqual(len(blinded), 3)
        service = ResponseService(
            responses,
            ScoreRepository(self.factory),
            EvaluatorRepository(self.factory),
        )
        first = service.next_unscored("E4")
        second = service.next_unscored("E4")
        self.assertEqual(first["response_id"], second["response_id"])
        self.assertTrue(set(first) <= BLINDED_RESPONSE_KEYS)
        self.assertNotIn("model_id", first)
        self.assertNotIn("provider", first)
        self.assertNotIn("repetition", first)
        self.assertTrue(first["blind_code"].startswith("R"))
        self.assertNotEqual(first["axis"], "lohusa")

    def test_progress_summary_counts(self) -> None:
        """Gruplanmış sayımlar eksen süzgeci ve puanlanan sayıyla tutarlıdır."""
        responses = ResponseRepository(self.factory)
        for question_id in ("Q1", "Q2", "Q3", "K1"):
            responses.add(question_id, "M1", 1, f"Metin {question_id}", 1, 1, "gpt-test")
        responses.assign_blind_codes(seed=3, expected_count=4)
        scores = ScoreRepository(self.factory)
        evaluators = EvaluatorRepository(self.factory)
        first = ResponseService(responses, scores, evaluators).next_unscored("E4")
        ScoringService(scores).submit(
            ScoreDraft(**{**_draft(first["response_id"]).__dict__, "evaluator_id": "E4"}),
            first["checklist"],
        )
        summary = ProgressService(responses, scores, evaluators).summary("E4")
        self.assertEqual(summary["total_responses"], 4)
        self.assertEqual(summary["assigned"], 3)
        self.assertEqual(summary["ready"], 3)
        self.assertEqual(summary["scored"], 1)
        self.assertEqual(summary["remaining"], 2)
        by_axis = {item["axis"]: item for item in summary["by_axis"]}
        self.assertEqual(by_axis["mutfak"]["assigned"], 2)
        self.assertEqual(by_axis["oruc"]["assigned"], 1)
        self.assertEqual(sum(item["scored"] for item in by_axis.values()), 1)

    def test_update_overwrites_score_and_keeps_evaluated_at(self) -> None:
        """Düzeltme aynı satırın üzerine yazar; ilk gönderim zamanı değişmez."""
        responses = ResponseRepository(self.factory)
        responses.add("Q1", "M1", 1, "Yanıt metni.", 10, 20, "gpt-test")
        responses.assign_blind_codes(seed=7, expected_count=1)
        items = [
            {"id": "a", "label": "Kritik", "category": "Kritik", "weight": 3},
            {"id": "b", "label": "Ek", "category": "Ek", "weight": 1},
        ]
        service = ScoringService(ScoreRepository(self.factory))
        original = _draft(1)
        original = ScoreDraft(
            response_id=1,
            evaluator_id="E1",
            gqs=original.gqs,
            checklist={"a": True, "b": False},
            cas=original.cas,
            safety_issue=False,
            safety_note=None,
            discern=original.discern,
        )
        service.submit(original, items)
        session = self.factory()
        try:
            stored = session.query(Score).one()
            evaluated_at = stored.evaluated_at
            score_id = stored.score_id
        finally:
            session.close()

        service.update(
            ScoreDraft(
                response_id=1,
                evaluator_id="E1",
                gqs=1,
                checklist={"a": False, "b": False},
                cas={item.key: 0 for item in CAS_ITEMS},
                safety_issue=True,
                safety_note="Düzeltildi",
                discern={item.key: 1 for item in DISCERN_ITEMS},
            ),
            items,
        )
        session = self.factory()
        try:
            rows = session.query(Score).all()
            self.assertEqual(len(rows), 1)
            score = rows[0]
            self.assertEqual(score.score_id, score_id)
            self.assertEqual(score.evaluated_at, evaluated_at)
            self.assertEqual(score.gqs, 1)
            self.assertEqual(score.cas_total, 0)
            self.assertEqual(score.discern_total, len(DISCERN_ITEMS))
            self.assertEqual(score.checklist_pct, 0.0)
            self.assertEqual(score.safety_note, "Düzeltildi")
        finally:
            session.close()

    def test_update_rejects_other_evaluator_and_invalid_values(self) -> None:
        """Başka uzmanın puanı ve geçersiz değer üzerine yazılmaz."""
        responses = ResponseRepository(self.factory)
        responses.add("Q1", "M1", 1, "Yanıt metni.", 10, 20, "gpt-test")
        service = ScoringService(ScoreRepository(self.factory))
        service.submit(_draft(1), [])
        with self.assertRaises(ScoringValidationError):
            service.update(
                ScoreDraft(**{**_draft(1).__dict__, "evaluator_id": "E2"}),
                [],
            )
        with self.assertRaises(ScoringValidationError):
            service.update(ScoreDraft(**{**_draft(1).__dict__, "gqs": 9}), [])
        session = self.factory()
        try:
            score = session.query(Score).one()
            self.assertEqual(score.evaluator_id, "E1")
            self.assertEqual(score.gqs, 4)
        finally:
            session.close()

    def test_scored_list_is_blind_and_edit_respects_axis(self) -> None:
        """Puan listesinde model yoktur; uzman kendi ekseni dışını düzeltemez."""
        responses = ResponseRepository(self.factory)
        scores = ScoreRepository(self.factory)
        evaluators = EvaluatorRepository(self.factory)
        for question_id in ("Q1", "Q3"):
            responses.add(question_id, "M1", 1, f"Metin {question_id}", 1, 1, "gpt-test")
        responses.assign_blind_codes(seed=3, expected_count=2)
        service = ResponseService(responses, scores, evaluators)
        scoring = ScoringService(scores)
        kitchen = service.next_unscored("E4")
        self.assertEqual(kitchen["axis"], "mutfak")
        scoring.submit(
            ScoreDraft(**{**_draft(kitchen["response_id"]).__dict__, "evaluator_id": "E4"}),
            kitchen["checklist"],
        )
        listed = scores.list_scored_for_evaluator("E4")
        self.assertEqual(set(listed[0]), {"response_id", "blind_code", "axis", "gqs"})
        self.assertNotIn("model_id", listed[0])
        self.assertTrue(listed[0]["blind_code"].startswith("R"))
        pair = service.scored_for_edit("E4", kitchen["response_id"])
        self.assertIsNotNone(pair)
        self.assertEqual(pair[1]["gqs"], 4)
        lohusa_id = next(
            item["response_id"]
            for item in responses.list_blinded_for_axes(["lohusa"])
        )
        scoring.submit(_draft(lohusa_id), [])
        self.assertIsNone(service.scored_for_edit("E4", lohusa_id))

    def test_safety_note_is_required(self) -> None:
        """Güvenlik sorunu işaretliyse boş açıklama kaydedilmez."""
        draft = _draft(1)
        draft = ScoreDraft(
            response_id=draft.response_id,
            evaluator_id=draft.evaluator_id,
            gqs=draft.gqs,
            checklist={},
            cas=draft.cas,
            safety_issue=True,
            safety_note="  ",
            discern=draft.discern,
        )
        with self.assertRaises(ScoringValidationError):
            ScoringService(ScoreRepository(self.factory)).submit(draft, [])


def _question_file() -> Path:
    """Üç soruluk geçici JSON yazar."""
    payload = {
        "source": "test",
        "questions": [
            {
                "id": "Q1",
                "type": "hasta_turevli",
                "axis": "mutfak",
                "sub_theme": "Deneme",
                "text": "Soru bir",
                "checklist": [{"id": "c1", "label": "Madde", "category": "Kritik"}],
            },
            {
                "id": "Q2",
                "type": "hasta_turevli",
                "axis": "oruc",
                "sub_theme": "Deneme",
                "text": "Soru iki",
                "checklist": [],
            },
            {
                "id": "Q3",
                "type": "hasta_turevli",
                "axis": "lohusa",
                "sub_theme": "Deneme",
                "text": "Soru üç",
                "checklist": [],
            },
            {
                "id": "K1",
                "type": "klavuz_vaka",
                "axis": "mutfak",
                "sub_theme": "Deneme",
                "text": "Vaka",
                "checklist": [],
            },
        ],
    }
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    import json

    json.dump(payload, handle, ensure_ascii=False)
    handle.close()
    return Path(handle.name)


def _draft(response_id: int) -> ScoreDraft:
    """Geçerli bir örnek puan üretir."""
    return ScoreDraft(
        response_id=response_id,
        evaluator_id="E1",
        gqs=4,
        checklist={},
        cas={item.key: 2 for item in CAS_ITEMS},
        safety_issue=False,
        safety_note=None,
        discern={item.key: 3 for item in DISCERN_ITEMS},
    )


if __name__ == "__main__":
    unittest.main()
