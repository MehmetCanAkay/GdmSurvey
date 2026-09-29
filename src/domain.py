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
    KLAVUZ_VAKA = "klavuz_vaka"


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
    QuestionType.KLAVUZ_VAKA: "Klavuz vakası",
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


# Kültürel uygunluk (0-2). Eski "içerik doğruluğu" maddelerinin yerini alır.
CAS_ITEMS: tuple[ScaleItem, ...] = (
    ScaleItem(
        "cas_food",
        "Beslenme ve mutfak",
        "Yöresel yiyecekler, öğün düzeni ve mutfak pratikleri Türkiye bağlamına uyuyor mu?",
    ),
    ScaleItem(
        "cas_religion",
        "Dini uygulamalar",
        "Oruç, sahur ve iftar gibi dini uygulamalar doğru ve saygılı ele alınmış mı?",
    ),
    ScaleItem(
        "cas_health_system",
        "Sağlık sistemi",
        "SGK, aile hekimi, eczane ve sevk süreçleri Türkiye sağlık sistemine uyuyor mu?",
    ),
    ScaleItem(
        "cas_local",
        "Yerel koşullar",
        "İklim, seyahat, ürün erişimi ve günlük yaşam koşulları yerelde geçerli mi?",
    ),
    ScaleItem(
        "cas_cultural",
        "Aile ve sosyal pratikler",
        "Misafirlik, aile baskısı ve aşerme gibi kültürel durumlar uygun ele alınmış mı?",
    ),
)

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
    cas: dict[str, int]
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
