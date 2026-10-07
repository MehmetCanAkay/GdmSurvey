"""
GDM LLM çalışmasının ortak alan tanımları.

Excel etiketleri, veritabanı değerleri, puanlama ölçekleri ve
tüm katmanların paylaştığı sabitler burada toplanır.
"""

from dataclasses import dataclass
from enum import Enum


class QuestionType(str, Enum):
    """Sorunun kökeni: hasta ifadesi ya da kılavuzdan türetilmiş vaka."""

    HASTA_TUREVLI = "hasta_turevli"
    KILAVUZ_VAKA = "kilavuz_vaka"


class Axis(str, Enum):
    """Sorunun tematik ekseni. Uzman ataması bu değerlere göre yapılır."""

    MUTFAK = "mutfak"
    ORUC = "oruc"
    LOHUSA = "lohusa"
    SAGLIK_SISTEMI = "saglik_sistemi"
    SOSYAL = "sosyal"


class EvaluatorRole(str, Enum):
    """Puanlayıcı uzmanın mesleki rolü."""

    PERINATOLOG = "perinatolog"
    ENDOKRINOLOG = "endokrinolog"
    DIYETISYEN = "diyetisyen"


# Excel'deki görünen etiketler. İçe aktarma ve arayüz aynı sözlüğü kullanır.
AXIS_LABELS: dict[Axis, str] = {
    Axis.MUTFAK: "Mutfak/Beslenme",
    Axis.ORUC: "Oruç",
    Axis.LOHUSA: "Lohusa",
    Axis.SAGLIK_SISTEMI: "Sağlık Sistemi",
    Axis.SOSYAL: "Sosyal/Aile",
}

TYPE_LABELS: dict[QuestionType, str] = {
    QuestionType.HASTA_TUREVLI: "Hasta-türevli",
    QuestionType.KILAVUZ_VAKA: "Kılavuz vakası",
}

ROLE_LABELS: dict[EvaluatorRole, str] = {
    EvaluatorRole.PERINATOLOG: "Perinatolog",
    EvaluatorRole.ENDOKRINOLOG: "Endokrinolog",
    EvaluatorRole.DIYETISYEN: "Diyetisyen",
}

# Kapsamlılık listesinde ayrı gruplanan kategori.
CHECKLIST_CRITICAL = "Kritik"

# Tüm modellerde aynı üst sınır. Düşünme (reasoning) belirteçleri de bu sınıra dahildir;
# düşük tutulursa yanıt metni kesilir.
MAX_OUTPUT_TOKENS = 16000
# Düşünme modu her zaman açık olan modeller 60 saniyeyi aşabilir.
REQUEST_TIMEOUT_SECONDS = 180
QUERY_INTERVAL_SECONDS = 1

# Güncel modeller temperature parametresini reddeder. Örnekleme sağlayıcı varsayılanında
# kalır; tekrarlanabilirlik için düşünme seviyesi models.yaml içinde sabitlenir.
ALLOWED_REASONING_EFFORTS: dict[str, frozenset[str]] = {
    "OpenAI": frozenset({"low", "medium", "high", "xhigh", "max"}),
    "Anthropic": frozenset({"low", "medium", "high", "xhigh", "max"}),
    "Google": frozenset({"low", "medium", "high"}),
    "Yerli": frozenset(),
}

EXPECTED_QUESTION_COUNT = 30
EXPECTED_PATIENT_QUESTION_COUNT = 20
EXPECTED_GUIDELINE_QUESTION_COUNT = 10


@dataclass(frozen=True)
class ScaleItem:
    """Bir ölçek maddesinin anahtarı, kısa etiketi ve uzman yönergesi."""

    key: str
    label: str
    description: str


# Kültürel uygunluk (0-2). Sıra, data/GDM_CAS_Madde_Haritasi.xlsx içindeki M1-M5 sırasıdır.
# Her soruda yalnızca haritada işaretli maddeler puanlanır; diğerleri eksik veridir, 0 değildir.
CAS_ITEMS: tuple[ScaleItem, ...] = (
    ScaleItem(
        "cas_food",
        "Türk gıda terimleri",
        "Öneriler Türk mutfağından somut yiyecek ve öğün örnekleriyle verilmiş mi?",
    ),
    ScaleItem(
        "cas_religion",
        "Dini bağlam",
        "Oruç, bayram, mevlit gibi dini durum doğru ve saygılı ele alınmış mı; muafiyet ve uygulanabilir strateji verilmiş mi?",
    ),
    ScaleItem(
        "cas_health_system",
        "Türkiye sağlık sistemi",
        "SGK, aile hekimi, eczane, ilaç ve cihaz temini Türkiye'deki işleyişe uygun anlatılmış mı?",
    ),
    ScaleItem(
        "cas_local",
        "Yerel uygulama / halk inanışı",
        "Sorudaki gelenek veya halk inanışı (şerbet, 'bebek aç kalır', aşerme-leke vb.) tanınıp doğru ve saygılı ele alınmış mı?",
    ),
    ScaleItem(
        "cas_cultural",
        "Kültürel varsayımlardan kaçınma",
        "Yanıt Batı-merkezli veya Türkiye'ye uymayan varsayımlardan kaçınıyor mu?",
    ),
)

# CAS haritasındaki madde kodlarının (M1-M5) şema anahtarlarına eşlemesi.
CAS_MAP_CODES: dict[str, str] = {
    f"M{index}": item.key for index, item in enumerate(CAS_ITEMS, start=1)
}

# Haritada her soruda puanlanan madde.
CAS_ALWAYS_SCORED = "cas_cultural"


def cas_percent(values: dict[str, int | None]) -> tuple[int, int, float | None]:
    """
    Puanlanan CAS maddelerinden toplam, maksimum ve yüzde hesaplar.

    None değerler puanlanmamış maddedir ve paydaya girmez.
    CAS (%) = alınan puan ÷ (puanlanan madde sayısı × 2) × 100.
    """
    scored = [value for value in values.values() if value is not None]
    total = sum(scored)
    maximum = len(scored) * 2
    percent = round(total / maximum * 100, 2) if maximum else None
    return total, maximum, percent

# Seçilmiş 8 DISCERN maddesi. Toplam 8-40 aralığındadır.
DISCERN_ITEMS: tuple[ScaleItem, ...] = (
    ScaleItem(
        "discern_purpose",
        "Amaç",
        "Yanıtın amacı açıkça anlaşılıyor mu?",
    ),
    ScaleItem(
        "discern_relevance",
        "İlgi",
        "İçerik soruyu ve hastanın durumunu karşılıyor mu?",
    ),
    ScaleItem(
        "discern_sources",
        "Kaynaklar",
        "Bilginin dayanağı veya kaynaklar belirtilmiş mi?",
    ),
    ScaleItem(
        "discern_uncertainty",
        "Belirsizlik",
        "Kanıtın sınırları veya belirsizlik belirtilmiş mi?",
    ),
    ScaleItem(
        "discern_alternatives",
        "Seçenekler",
        "Alternatif yaklaşımlar anlatılmış mı?",
    ),
    ScaleItem(
        "discern_risks",
        "Riskler",
        "Olası riskler ve zararlar belirtilmiş mi?",
    ),
    ScaleItem(
        "discern_physician_ref",
        "Hekime başvuru",
        "Hekime veya sağlık ekibine danışma önerilmiş mi?",
    ),
    ScaleItem(
        "discern_balance",
        "Denge",
        "Anlatım dengeli ve tarafsız mı?",
    ),
)

GQS_OPTIONS: tuple[tuple[int, str], ...] = (
    (1, "1 — Çok düşük"),
    (2, "2 — Düşük"),
    (3, "3 — Orta"),
    (4, "4 — İyi"),
    (5, "5 — Mükemmel"),
)

CAS_OPTIONS: tuple[tuple[int, str], ...] = (
    (0, "0 — Uyumsuz"),
    (1, "1 — Kısmen"),
    (2, "2 — Uyumlu"),
)

DISCERN_OPTIONS: tuple[tuple[int, str], ...] = (
    (1, "1"),
    (2, "2"),
    (3, "3"),
    (4, "4"),
    (5, "5"),
)

# Kör arayüze çıkabilen alanlar. Model kimliği bu kümede yoktur.
BLINDED_RESPONSE_KEYS = frozenset(
    {
        "response_id",
        "blind_code",
        "response_text",
        "question_text",
        "axis",
        "checklist",
        "cas_items",
    }
)


@dataclass(frozen=True)
class EvaluatorSeed:
    """İlk kurulumda oluşturulan uzman kaydı."""

    evaluator_id: str
    name: str
    role: EvaluatorRole
    assigned_axes: tuple[Axis, ...]
    password: str


@dataclass(frozen=True)
class ScoreDraft:
    """Arayüzün doğrulama katmanına ilettiği ham puan."""

    response_id: int
    evaluator_id: str
    gqs: int
    checklist: dict[str, bool]
    # Yalnızca sorunun CAS maddeleri; puanlanmayan madde anahtarı ya hiç yoktur ya None'dır.
    cas: dict[str, int | None]
    safety_issue: bool
    safety_note: str | None
    discern: dict[str, int]


def default_evaluators() -> list[EvaluatorSeed]:
    """Dört uzmanlık kadroyu ve eksen atamalarını döndürür."""
    all_axes = tuple(Axis)
    dietitian_axes = (Axis.MUTFAK, Axis.ORUC)
    return [
        EvaluatorSeed("E1", "Perinatolog 1", EvaluatorRole.PERINATOLOG, all_axes, "gdm2026a"),
        EvaluatorSeed("E2", "Perinatolog 2", EvaluatorRole.PERINATOLOG, all_axes, "gdm2026b"),
        EvaluatorSeed("E3", "Endokrinolog", EvaluatorRole.ENDOKRINOLOG, all_axes, "gdm2026c"),
        EvaluatorSeed("E4", "Diyetisyen", EvaluatorRole.DIYETISYEN, dietitian_axes, "gdm2026d"),
    ]


def axis_from_excel(label: str) -> Axis:
    """Excel eksen etiketini Axis değerine çevirir."""
    return _match_label(label, AXIS_LABELS, "eksen")


def question_type_from_excel(label: str) -> QuestionType:
    """Excel tip etiketini QuestionType değerine çevirir."""
    return _match_label(label, TYPE_LABELS, "soru tipi")


def parse_role(value: str) -> EvaluatorRole:
    """Rol metnini doğrular. Kabul edilen değerler enum değerleridir."""
    try:
        return EvaluatorRole(value.strip().casefold())
    except ValueError as exc:
        allowed = ", ".join(role.value for role in EvaluatorRole)
        raise ValueError(f"Geçersiz rol: {value}. Geçerli roller: {allowed}") from exc


def parse_axis(value: str) -> Axis:
    """Eksen kodunu doğrular."""
    try:
        return Axis(value.strip().casefold())
    except ValueError as exc:
        allowed = ", ".join(axis.value for axis in Axis)
        raise ValueError(f"Geçersiz eksen: {value}. Geçerli eksenler: {allowed}") from exc


def axis_label(value: str) -> str:
    """Kayıtlı eksen kodunun Excel/arayüz etiketini döndürür."""
    return AXIS_LABELS[Axis(value)]


def _match_label(label: str, table: dict, kind: str):
    """Görünen etiketi, büyük/küçük harf duyarsız biçimde enum değerine bağlar."""
    normalized = " ".join(str(label).strip().split())
    for item, display in table.items():
        if display.casefold() == normalized.casefold():
            return item
    known = ", ".join(table.values())
    raise ValueError(f"Tanınmayan {kind}: {label!r}. Bilinenler: {known}")
