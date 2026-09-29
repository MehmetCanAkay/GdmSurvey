"""
Türkçe okunabilirlik ölçümleri.

Ateşman (1997) ve Bezirci-Yılmaz (2010) formülleri.
LLM çıktısındaki markdown, ölçüme girmeden temizlenir.
Hece sayısı, Türkçe sesli harf sayısına eşittir.
"""

import math
import re
from decimal import Decimal, ROUND_HALF_UP

TURKISH_VOWELS = set("aeıioöuüâîûAEIİOÖUÜÂÎÛ")

_ABBREVIATIONS = (
    "dr",
    "prof",
    "doç",
    "doc",
    "uzm",
    "yrd",
    "vb",
    "vs",
    "örn",
    "orn",
    "bkz",
    "çev",
    "cev",
    "no",
    "sn",
    "hz",
)
_ABBREVIATION_PATTERN = re.compile(
    r"\b(?:" + "|".join(_ABBREVIATIONS) + r")\.",
    re.IGNORECASE,
)
_DECIMAL_PATTERN = re.compile(r"(?<=\d)\.(?=\d)")
_WORD_PATTERN = re.compile(r"[a-zA-ZçÇğĞıİöÖşŞüÜâÂîÎûÛ]+")
_PLACEHOLDER = "\u0000{}\u0000"


def clean_markdown(text: str) -> str:
    """
    Markdown izlerini düz metne çevirir.

    Liste maddeleri ve başlıklar ayrı cümle kabul edilir.
    Aynı paragrafın satır sonları birleştirilir. Tablo satırları atılır.
    """
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    sentences: list[str] = []
    paragraph: list[str] = []
    for raw_line in text.split("\n"):
        if raw_line.count("|") >= 2:
            continue
        is_list = bool(re.match(r"^\s*(?:[-+*]|\d+[.)])\s+\S", raw_line))
        is_heading = bool(re.match(r"^#{1,6}\s+\S", raw_line))
        line = _strip_markdown_line(raw_line)
        if not line:
            _flush_paragraph(paragraph, sentences)
            continue
        if is_list or is_heading:
            _flush_paragraph(paragraph, sentences)
            sentences.append(_ensure_terminal(line))
        else:
            paragraph.append(line)
    _flush_paragraph(paragraph, sentences)
    return " ".join(sentences)


def _strip_markdown_line(raw_line: str) -> str:
    """Tek satırdaki markdown işaretlerini kaldırır."""
    line = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", raw_line)
    line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)
    line = re.sub(r"^#{1,6}\s*", "", line)
    line = line.replace("**", "").replace("__", "").replace("`", "")
    line = line.replace("*", "")
    line = re.sub(r"^\s*[-+]\s+", "", line)
    line = re.sub(r"^\s*\d+[.)]\s+", "", line)
    return " ".join(line.split())


def _flush_paragraph(paragraph: list[str], sentences: list[str]) -> None:
    """Birikmiş paragraf satırlarını tek cümle olarak ekler."""
    if not paragraph:
        return
    sentences.append(_ensure_terminal(" ".join(paragraph)))
    paragraph.clear()


def _ensure_terminal(line: str) -> str:
    """Cümle . ! veya ? ile bitmiyorsa nokta ekler."""
    if line[-1] not in ".!?":
        return line + "."
    return line


def count_syllables(word: str) -> int:
    """Kelimedeki sesli harf sayısını, en az 1 olmak üzere döndürür."""
    count = sum(1 for char in word if char in TURKISH_VOWELS)
    return max(1, count)


def tokenize_words(text: str) -> list[str]:
    """Temizlenmiş metindeki kelimeleri döndürür."""
    return _WORD_PATTERN.findall(clean_markdown(text))


def tokenize_sentences(text: str) -> list[str]:
    """
    Cümlelere ayırır.

    Ondalık sayılar ve Dr. gibi kısaltmalar cümle sonu sayılmaz.
    """
    cleaned = clean_markdown(text)
    if not cleaned:
        return []
    protected, tokens = _protect(cleaned)
    parts = re.split(r"[.!?]+", protected)
    sentences = []
    for part in parts:
        restored = _restore(part, tokens).strip()
        if restored:
            sentences.append(restored)
    return sentences


def word_count(text: str) -> int:
    """Kelime sayısı."""
    return len(tokenize_words(text))


def sentence_count(text: str) -> int:
    """Cümle sayısı. Boş metinde 0 döner."""
    return len(tokenize_sentences(text))


def average_word_length_syllables(text: str) -> float:
    """Kelime başına ortalama hece."""
    words = tokenize_words(text)
    if not words:
        return 0.0
    return sum(count_syllables(word) for word in words) / len(words)


def average_sentence_length_words(text: str) -> float:
    """Cümle başına ortalama kelime."""
    words = tokenize_words(text)
    sentences = tokenize_sentences(text)
    if not words or not sentences:
        return 0.0
    return len(words) / len(sentences)


def syllable_rates(text: str) -> dict[str, float]:
    """
    Cümle başına ortalama 3, 4, 5 ve 6+ heceli kelime sayısı.

    Bezirci-Yılmaz formülündeki H3..H6 terimleri bu değerlerdir.
    """
    sentences = tokenize_sentences(text)
    totals = {"h3": 0, "h4": 0, "h5": 0, "h6": 0}
    for sentence in sentences:
        for word in _WORD_PATTERN.findall(sentence):
            syllables = count_syllables(word)
            if syllables >= 6:
                totals["h6"] += 1
            elif syllables == 5:
                totals["h5"] += 1
            elif syllables == 4:
                totals["h4"] += 1
            elif syllables == 3:
                totals["h3"] += 1
    count = len(sentences)
    if count == 0:
        return totals
    return {key: value / count for key, value in totals.items()}


def atesman_score(text: str) -> float:
    """
    Ateşman okunabilirlik puanı (1997).

    198.825 - 40.175 × (hece/kelime) - 2.610 × (kelime/cümle)
    """
    words = tokenize_words(text)
    sentences = tokenize_sentences(text)
    if not words or not sentences:
        return 0.0
    syllables = sum(count_syllables(word) for word in words)
    score = (
        Decimal("198.825")
        - Decimal("40.175") * Decimal(syllables) / Decimal(len(words))
        - Decimal("2.610") * Decimal(len(words)) / Decimal(len(sentences))
    )
    return float(score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def bezirci_yilmaz_grade(text: str) -> float:
    """
    Bezirci-Yılmaz okunabilirlik düzeyi (2010).

    karekök( OKS × (0.84×H3 + 1.5×H4 + 3.5×H5 + 26.25×H6) )

    OKS cümle başına kelime, Hn cümle başına n heceli kelime sayısıdır.
    H6, altı ve daha fazla heceli kelimeleri toplar.
    """
    words = tokenize_words(text)
    if not words:
        return 0.0
    rates = syllable_rates(text)
    oks = average_sentence_length_words(text)
    weighted = (
        (0.84 * rates["h3"])
        + (1.5 * rates["h4"])
        + (3.5 * rates["h5"])
        + (26.25 * rates["h6"])
    )
    return round(math.sqrt(oks * weighted), 2)


def analyze_text(text: str) -> dict:
    """Bir metnin okunabilirlik ölçümlerinin tamamını döndürür."""
    rates = syllable_rates(text)
    return {
        "word_count": word_count(text),
        "sentence_count": sentence_count(text),
        "atesman_score": atesman_score(text),
        "bezirci_yilmaz_grade": bezirci_yilmaz_grade(text),
        "avg_word_length_syllables": round(average_word_length_syllables(text), 2),
        "avg_sentence_length_words": round(average_sentence_length_words(text), 2),
        "h3": round(rates["h3"], 4),
        "h4": round(rates["h4"], 4),
        "h5": round(rates["h5"], 4),
        "h6": round(rates["h6"], 4),
    }


def _protect(text: str) -> tuple[str, list[str]]:
    """Cümle sonu sanılabilecek noktaları yer tutucu ile değiştirir."""
    tokens: list[str] = []

    def hold(match: re.Match) -> str:
        """Eşleşen parçayı sıradaki yer tutucu ile değiştirir."""
        tokens.append(match.group(0))
        return _PLACEHOLDER.format(len(tokens) - 1)

    protected = _ABBREVIATION_PATTERN.sub(hold, text)
    protected = _DECIMAL_PATTERN.sub(hold, protected)
    return protected, tokens


def _restore(text: str, tokens: list[str]) -> str:
    """Yer tutucuları özgün metinle değiştirir."""

    def put(match: re.Match) -> str:
        """Yer tutucu numarasındaki özgün parçayı geri yazar."""
        return tokens[int(match.group(1))]

    return re.sub(r"\u0000(\d+)\u0000", put, text)
