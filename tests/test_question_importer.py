"""Excel'den soru aktarımı ve checklist koruması."""

import json
import tempfile
import unittest
from pathlib import Path

from src.question_importer import EXCEL_FILENAME, QuestionImportError, import_questions

ROOT = Path(__file__).resolve().parent.parent
EXCEL = ROOT / "data" / EXCEL_FILENAME


class QuestionImporterTests(unittest.TestCase):
    """30 soruluk havuzun Excel ile birebir geldiğini denetler."""

    def test_imports_thirty_questions_in_excel_order(self) -> None:
        """20 hasta-türevli ve 10 kılavuz vakası, Q1 metni korunarak yazılır."""
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "questions.json"
            payload = import_questions(EXCEL, target)
        self.assertEqual(len(payload["questions"]), 30)
        self.assertEqual(payload["source"], EXCEL_FILENAME)
        first = payload["questions"][0]
        self.assertEqual(first["id"], "Q1")
        self.assertEqual(first["axis"], "mutfak")
        self.assertEqual(first["type"], "hasta_turevli")
        self.assertTrue(first["text"].startswith("Gebelik şekerim var"))
        self.assertEqual(payload["questions"][20]["id"], "K1")
        self.assertEqual(
            sum(1 for question in payload["questions"] if question["type"] == "klavuz_vaka"),
            10,
        )

    def test_existing_checklist_is_preserved(self) -> None:
        """Aynı soru kimliğindeki checklist, Excel yenilense de durur."""
        checklist = [{"id": "c1", "label": "175 g karbonhidrat", "category": "Kritik"}]
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "questions.json"
            target.write_text(
                json.dumps(
                    {
                        "source": "eski",
                        "questions": [{"id": "Q1", "checklist": checklist}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            payload = import_questions(EXCEL, target)
        q1 = next(question for question in payload["questions"] if question["id"] == "Q1")
        self.assertEqual(q1["checklist"], checklist)
        q2 = next(question for question in payload["questions"] if question["id"] == "Q2")
        self.assertEqual(q2["checklist"], [])

    def test_broken_checklist_is_rejected(self) -> None:
        """Eksik alanlı checklist sessizce silinmez."""
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "questions.json"
            target.write_text(
                json.dumps({"questions": [{"id": "Q1", "checklist": [{"id": "c1"}]}]}),
                encoding="utf-8",
            )
            with self.assertRaises(QuestionImportError):
                import_questions(EXCEL, target)


if __name__ == "__main__":
    unittest.main()
