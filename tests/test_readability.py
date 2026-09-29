"""Ateşman, Bezirci-Yılmaz ve markdown temizliği testleri."""

import unittest

from src.readability import (
    analyze_text,
    atesman_score,
    bezirci_yilmaz_grade,
    sentence_count,
    tokenize_words,
)


class ReadabilityTests(unittest.TestCase):
    """Elle hesaplanmış kısa metinlerle formülleri denetler."""

    def test_atesman_two_sentences(self) -> None:
        """Dört iki heceli kelime, iki cümle: 198.825 - 80.35 - 5.22 = 113.26."""
        text = "Ali geldi. Veli gitti."
        self.assertEqual(atesman_score(text), 113.26)
        self.assertEqual(bezirci_yilmaz_grade(text), 0.0)

    def test_bezirci_four_syllable_word(self) -> None:
        """Hastaneye 4 hece, gitti 2 hece. YOD = karekök(2 × 1.5) = 1.73."""
        text = "Hastaneye gitti."
        self.assertEqual(atesman_score(text), 73.08)
        self.assertEqual(bezirci_yilmaz_grade(text), 1.73)
        metrics = analyze_text(text)
        self.assertEqual(metrics["h4"], 1.0)
        self.assertEqual(metrics["h3"], 0.0)

    def test_abbreviation_and_decimal_do_not_split(self) -> None:
        """Dr. ve 1.5 cümle sonu değildir."""
        self.assertEqual(sentence_count("Dr. Ayşe geldi. Sonra gitti."), 2)
        self.assertEqual(sentence_count("Şeker 1.5 olur. Sonra diner."), 2)

    def test_markdown_list_becomes_sentences(self) -> None:
        """Liste maddeleri ayrı cümle sayılır, kalın işaret kalkar."""
        text = "- Elma yiyin\n- Armut yiyin\n**kalın** kelime kaldı."
        self.assertEqual(sentence_count(text), 3)
        words = tokenize_words(text)
        self.assertIn("kalın", words)
        self.assertNotIn("**kalın**", words)


if __name__ == "__main__":
    unittest.main()
