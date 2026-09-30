"""
GDM LLM çalışması veritabanı.

SQLAlchemy ORM ile altı tablo ve bunlara erişen repository sınıfları.
Oturum fabrikası dışarıdan verilir; çağıran katman bağımlılığı kendisi kurar.
"""

import hashlib
import json
import os
import random
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from dotenv import load_dotenv
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker
from sqlalchemy.pool import NullPool

from src.domain import (
    BLINDED_RESPONSE_KEYS,
    CAS_ITEMS,
    DISCERN_ITEMS,
    EvaluatorRole,
    EvaluatorSeed,
    default_evaluators,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Kabuktaki değerler .env'deki değerlerin önüne geçer.
load_dotenv(PROJECT_ROOT / ".env", override=False)

DATA_DIR = PROJECT_ROOT / "data"
PILOT_DB_PATH = DATA_DIR / "pilot.db"
# GDM_DB_FILE, arayüzü pilot veritabanıyla açmak için kullanılır.
DB_PATH = Path(os.getenv("GDM_DB_FILE") or DATA_DIR / "study.db")

# Streamlit Cloud'da DATABASE_URL varsa PostgreSQL, yoksa yerel SQLite.
DATABASE_URL = os.getenv("DATABASE_URL")


def sqlite_engine(path: Path):
    """Verilen dosya için SQLite motoru kurar."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{path}", echo=False)


if DATABASE_URL:
    # Transaction pooler boşta kalan bağlantıyı keser; havuz kullanılmaz.
    ENGINE = create_engine(
        DATABASE_URL,
        echo=False,
        poolclass=NullPool,
        pool_pre_ping=True,
    )
else:
    ENGINE = sqlite_engine(DB_PATH)

SessionLocal = sessionmaker(bind=ENGINE)


class Base(DeclarativeBase):
    """Tüm tabloların ortak tabanı."""


class Question(Base):
    """Excel'den gelen 30 soru."""

    __tablename__ = "questions"

    question_id = Column(String(10), primary_key=True)
    question_text = Column(Text, nullable=False)
    type = Column(String(30), nullable=False)
    axis = Column(String(50), nullable=False)
    sub_theme = Column(String(200), nullable=False, default="")
    checklist_json = Column(Text, nullable=False, default="[]")

    responses = relationship("Response", back_populates="question")


class Model(Base):
    """Çalışmada sabitlenen dil modeli."""

    __tablename__ = "models"

    model_id = Column(String(10), primary_key=True)
    provider = Column(String(50), nullable=False)
    model_string = Column(String(100), nullable=False)
    # NULL: temperature gönderilmedi, sağlayıcı varsayılanı kullanıldı.
    temperature = Column(Float, nullable=True)
    reasoning_effort = Column(String(20), nullable=True)
    system_prompt = Column(Text, nullable=True)

    responses = relationship("Response", back_populates="model")


class Response(Base):
    """Bir soruya bir modelin bir tekrarında verdiği yanıt."""

    __tablename__ = "responses"
    __table_args__ = (
        UniqueConstraint(
            "question_id",
            "model_id",
            "repetition",
            name="uq_response_question_model_repetition",
        ),
    )

    response_id = Column(Integer, primary_key=True, autoincrement=True)
    question_id = Column(String(10), ForeignKey("questions.question_id"), nullable=False)
    model_id = Column(String(10), ForeignKey("models.model_id"), nullable=False)
    repetition = Column(Integer, nullable=False)
    response_text = Column(Text, nullable=False)
    timestamp = Column(DateTime, nullable=False)
    tokens_used = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    # Toplu atamaya kadar boş kalabilir. SQLite birden fazla NULL değere izin verir.
    blind_code = Column(String(10), unique=True, nullable=True)
    model_version_returned = Column(String(100), nullable=True)
    finish_reason = Column(String(40), nullable=True)

    question = relationship("Question", back_populates="responses")
    model = relationship("Model", back_populates="responses")
    scores = relationship("Score", back_populates="response")
    readability = relationship("ReadabilityMetric", back_populates="response", uselist=False)


class Evaluator(Base):
    """Kör puanlama yapan uzman."""

    __tablename__ = "evaluators"

    evaluator_id = Column(String(10), primary_key=True)
    name = Column(String(100), nullable=False)
    role = Column(String(50), nullable=False)
    assigned_axes = Column(Text, nullable=False)
    password_hash = Column(String(128), nullable=False)

    scores = relationship("Score", back_populates="evaluator")


class Score(Base):
    """Bir uzmanın bir yanıta verdiği puan."""

    __tablename__ = "scores"
    __table_args__ = (
        UniqueConstraint(
            "response_id",
            "evaluator_id",
            name="uq_score_response_evaluator",
        ),
    )

    score_id = Column(Integer, primary_key=True, autoincrement=True)
    response_id = Column(Integer, ForeignKey("responses.response_id"), nullable=False)
    evaluator_id = Column(String(10), ForeignKey("evaluators.evaluator_id"), nullable=False)
    gqs = Column(Integer, nullable=False)
    checklist_json = Column(Text, nullable=False, default="{}")
    checklist_pct = Column(Float, nullable=True)
    checklist_weighted_pct = Column(Float, nullable=True)
    cas_food = Column(Integer, nullable=False)
    cas_religion = Column(Integer, nullable=False)
    cas_health_system = Column(Integer, nullable=False)
    cas_local = Column(Integer, nullable=False)
    cas_cultural = Column(Integer, nullable=False)
    cas_total = Column(Integer, nullable=False)
    safety_issue = Column(Boolean, nullable=False, default=False)
    safety_note = Column(Text, nullable=True)
    discern_purpose = Column(Integer, nullable=False)
    discern_relevance = Column(Integer, nullable=False)
    discern_sources = Column(Integer, nullable=False)
    discern_uncertainty = Column(Integer, nullable=False)
    discern_alternatives = Column(Integer, nullable=False)
    discern_risks = Column(Integer, nullable=False)
    discern_physician_ref = Column(Integer, nullable=False)
    discern_balance = Column(Integer, nullable=False)
    discern_total = Column(Integer, nullable=False)
    evaluated_at = Column(DateTime, nullable=False)

    response = relationship("Response", back_populates="scores")
    evaluator = relationship("Evaluator", back_populates="scores")


class ReadabilityMetric(Base):
    """Yanıt metninden otomatik hesaplanan okunabilirlik ölçümleri."""

    __tablename__ = "readability"

    response_id = Column(Integer, ForeignKey("responses.response_id"), primary_key=True)
    atesman_score = Column(Float, nullable=True)
    bezirci_yilmaz_grade = Column(Float, nullable=True)
    word_count = Column(Integer, nullable=True)
    sentence_count = Column(Integer, nullable=True)
    h3 = Column(Float, nullable=True)
    h4 = Column(Float, nullable=True)
    h5 = Column(Float, nullable=True)
    h6 = Column(Float, nullable=True)

    response = relationship("Response", back_populates="readability")


def init_db(engine=None) -> None:
    """Tabloları oluşturur. Var olan tablolara dokunmaz."""
    Base.metadata.create_all(engine or ENGINE)


def utc_now() -> datetime:
    """UTC zaman damgası üretir."""
    return datetime.now(timezone.utc)


def _hash_password(password: str) -> str:
    """Yerel çalışma şifresini SHA-256 ile özetler. API anahtarı değildir."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


class _Repository:
    """Oturum açıp kapatan ortak taban."""

    def __init__(self, session_factory: sessionmaker):
        """Verilen oturum fabrikasıyla repository oluşturur."""
        self._session_factory = session_factory

    @contextmanager
    def _session(self):
        """İşlem sonunda commit, hata durumunda rollback yapan oturum."""
        session: Session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


class QuestionRepository(_Repository):
    """Soru kayıtlarını JSON ile eşitler."""

    def upsert_from_json(self, json_path: Path) -> int:
        """JSON'daki soruları ekler veya metin alanlarını günceller."""
        payload = json.loads(Path(json_path).read_text(encoding="utf-8"))
        questions = payload["questions"] if isinstance(payload, dict) else payload
        with self._session() as session:
            for item in questions:
                checklist = json.dumps(item.get("checklist") or [], ensure_ascii=False)
                existing = session.get(Question, item["id"])
                if existing is None:
                    session.add(
                        Question(
                            question_id=item["id"],
                            question_text=item["text"],
                            type=item["type"],
                            axis=item["axis"],
                            sub_theme=item.get("sub_theme") or "",
                            checklist_json=checklist,
                        )
                    )
                else:
                    existing.question_text = item["text"]
                    existing.type = item["type"]
                    existing.axis = item["axis"]
                    existing.sub_theme = item.get("sub_theme") or ""
                    existing.checklist_json = checklist
        return len(questions)

    def list_records(self) -> list[dict]:
        """Sorgu motorunun kullanacağı sade soru kayıtları."""
        with self._session() as session:
            rows = session.query(Question).all()
            records = [
                {
                    "question_id": row.question_id,
                    "question_text": row.question_text,
                    "axis": row.axis,
                    "type": row.type,
                }
                for row in rows
            ]
        return _sort_question_ids(records)

    def count(self) -> int:
        """Kayıtlı soru sayısını döndürür."""
        with self._session() as session:
            return session.query(Question).count()


class ModelRepository(_Repository):
    """Model tanımlarını YAML içeriğinden eşitler."""

    def upsert_many(self, models: list[dict]) -> int:
        """Model kimliğine göre ekler veya sürüm bilgisini günceller."""
        with self._session() as session:
            for item in models:
                existing = session.get(Model, item["model_id"])
                if existing is None:
                    session.add(
                        Model(
                            model_id=item["model_id"],
                            provider=item["provider"],
                            model_string=item["model_string"],
                            temperature=item.get("temperature"),
                            reasoning_effort=item.get("reasoning_effort"),
                            system_prompt=item.get("system_prompt"),
                        )
                    )
                else:
                    existing.provider = item["provider"]
                    existing.model_string = item["model_string"]
                    existing.temperature = item.get("temperature")
                    existing.reasoning_effort = item.get("reasoning_effort")
                    existing.system_prompt = item.get("system_prompt")
        return len(models)

    def list_records(self) -> list[dict]:
        """Sorgu motorunun kullanacağı model kayıtları."""
        with self._session() as session:
            rows = session.query(Model).order_by(Model.model_id).all()
            return [
                {
                    "model_id": row.model_id,
                    "provider": row.provider,
                    "model_string": row.model_string,
                }
                for row in rows
            ]

    def count(self) -> int:
        """Kayıtlı model sayısını döndürür."""
        with self._session() as session:
            return session.query(Model).count()


class ResponseRepository(_Repository):
    """Yanıt, okunabilirlik ve kör kod işlemleri."""

    def add(
        self,
        question_id: str,
        model_id: str,
        repetition: int,
        response_text: str,
        tokens_used: int | None,
        latency_ms: int | None,
        model_version_returned: str | None,
        finish_reason: str | None = None,
    ) -> int:
        """Yeni yanıt ekler. Kör kod daha sonra toplu atanır."""
        with self._session() as session:
            response = Response(
                question_id=question_id,
                model_id=model_id,
                repetition=repetition,
                response_text=response_text,
                timestamp=utc_now(),
                tokens_used=tokens_used,
                latency_ms=latency_ms,
                blind_code=None,
                model_version_returned=model_version_returned,
                finish_reason=finish_reason,
            )
            session.add(response)
            session.flush()
            return response.response_id

    def exists(self, question_id: str, model_id: str, repetition: int) -> bool:
        """Bu soru-model-tekrar üçlüsü daha önce kaydedildiyse True döner."""
        with self._session() as session:
            found = (
                session.query(Response.response_id)
                .filter_by(question_id=question_id, model_id=model_id, repetition=repetition)
                .first()
            )
            return found is not None

    def existing_keys(self) -> set[tuple[str, str, int]]:
        """Kayıtlı tüm (soru, model, tekrar) üçlülerini tek sorguda döndürür."""
        with self._session() as session:
            rows = session.query(Response.question_id, Response.model_id, Response.repetition).all()
            return {(question_id, model_id, repetition) for question_id, model_id, repetition in rows}

    def count(self) -> int:
        """Toplam yanıt sayısı."""
        with self._session() as session:
            return session.query(Response).count()

    def count_for_axes(self, axes: list[str]) -> int:
        """Verilen eksenlerdeki yanıt sayısı."""
        with self._session() as session:
            return (
                session.query(Response)
                .join(Question)
                .filter(Question.axis.in_(axes))
                .count()
            )

    def count_by_axis(self) -> dict[str, int]:
        """Eksen başına yanıt sayısı."""
        with self._session() as session:
            rows = session.query(Question.axis, Response.response_id).join(Response).all()
            counts: dict[str, int] = {}
            for axis, _response_id in rows:
                counts[axis] = counts.get(axis, 0) + 1
            return counts

    def add_readability(self, response_id: int, metrics: dict) -> None:
        """Bir yanıtın okunabilirlik ölçümlerini yazar."""
        with self._session() as session:
            session.add(
                ReadabilityMetric(
                    response_id=response_id,
                    atesman_score=metrics["atesman_score"],
                    bezirci_yilmaz_grade=metrics["bezirci_yilmaz_grade"],
                    word_count=metrics["word_count"],
                    sentence_count=metrics["sentence_count"],
                    h3=metrics["h3"],
                    h4=metrics["h4"],
                    h5=metrics["h5"],
                    h6=metrics["h6"],
                )
            )

    def assign_blind_codes(self, seed: int, expected_count: int) -> int:
        """
        Yanıtlara R001'den başlayan karışık kör kod atar.

        Yanıt sayısı expected_count ile aynı olmalıdır.
        Herhangi bir kod daha önce atandıysa işlem yapılmaz.
        """
        with self._session() as session:
            rows = session.query(Response).order_by(Response.response_id).all()
            if len(rows) != expected_count:
                raise ValueError(
                    f"Kör kod için {expected_count} yanıt bekleniyor, kayıtlı sayı {len(rows)}."
                )
            if any(row.blind_code for row in rows):
                raise ValueError("Kör kodlar zaten atanmış. Yeniden atama yapılmadı.")
            order = [row.response_id for row in rows]
            random.Random(seed).shuffle(order)
            by_id = {row.response_id: row for row in rows}
            for index, response_id in enumerate(order, start=1):
                by_id[response_id].blind_code = f"R{index:03d}"
            return len(rows)

    def list_blinded_for_axes(self, axes: list[str]) -> list[dict]:
        """
        Uzmana gösterilebilecek yanıtlar.

        Model, sağlayıcı ve tekrar numarası bu sözlüklere konmaz.
        Kör kodu olmayan yanıtlar puanlamaya kapalıdır.
        """
        with self._session() as session:
            rows = (
                session.query(Response, Question)
                .join(Question, Response.question_id == Question.question_id)
                .filter(Question.axis.in_(axes))
                .filter(Response.blind_code.isnot(None))
                .all()
            )
            blinded = [_blinded_payload(response, question) for response, question in rows]
        for item in blinded:
            unexpected = set(item) - BLINDED_RESPONSE_KEYS
            if unexpected:
                raise RuntimeError(f"Kör yanıta model bilgisi karıştı: {unexpected}")
        return blinded


class EvaluatorRepository(_Repository):
    """Uzman kimliği, şifre ve eksen ataması."""

    def add(
        self,
        evaluator_id: str,
        name: str,
        role: str,
        assigned_axes: list[str],
        password: str,
    ) -> None:
        """Yeni uzman ekler. Rol değeri enum ile doğrulanmış olmalıdır."""
        EvaluatorRole(role)
        with self._session() as session:
            session.add(
                Evaluator(
                    evaluator_id=evaluator_id,
                    name=name,
                    role=role,
                    assigned_axes=json.dumps(assigned_axes, ensure_ascii=False),
                    password_hash=_hash_password(password),
                )
            )

    def seed_defaults(self, seeds: list[EvaluatorSeed] | None = None) -> list[EvaluatorSeed]:
        """
        Eksik varsayılan uzmanları ekler.

        Dönüş: bu çağrıda yeni eklenenler. Şifre yalnızca çağıran tarafından,
        bir kez gösterilmelidir. Burada loglanmaz.
        """
        created: list[EvaluatorSeed] = []
        with self._session() as session:
            for seed in seeds or default_evaluators():
                if session.get(Evaluator, seed.evaluator_id) is not None:
                    continue
                session.add(
                    Evaluator(
                        evaluator_id=seed.evaluator_id,
                        name=seed.name,
                        role=seed.role.value,
                        assigned_axes=json.dumps(
                            [axis.value for axis in seed.assigned_axes],
                            ensure_ascii=False,
                        ),
                        password_hash=_hash_password(seed.password),
                    )
                )
                created.append(seed)
        return created

    def authenticate(self, username: str, password: str) -> dict | None:
        """Kimlik veya ad ile girişi doğrular. Başarısızsa None döner."""
        with self._session() as session:
            evaluator = (
                session.query(Evaluator)
                .filter((Evaluator.evaluator_id == username) | (Evaluator.name == username))
                .first()
            )
            if evaluator is None or evaluator.password_hash != _hash_password(password):
                return None
            return _evaluator_dict(evaluator)

    def get(self, evaluator_id: str) -> dict | None:
        """Uzman kaydını sözlük olarak döndürür."""
        with self._session() as session:
            evaluator = session.get(Evaluator, evaluator_id)
            if evaluator is None:
                return None
            return _evaluator_dict(evaluator)

    def list_all(self) -> list[dict]:
        """Şifre içermeyen uzman listesi."""
        with self._session() as session:
            rows = session.query(Evaluator).order_by(Evaluator.evaluator_id).all()
            return [_evaluator_dict(row) for row in rows]

    def reset_password(self, evaluator_id: str, new_password: str) -> bool:
        """Şifreyi günceller. Uzman yoksa False döner."""
        with self._session() as session:
            evaluator = session.get(Evaluator, evaluator_id)
            if evaluator is None:
                return False
            evaluator.password_hash = _hash_password(new_password)
            return True


class ScoreRepository(_Repository):
    """Puan kayıtları."""

    def add(self, payload: dict) -> int:
        """Doğrulanmış puanı yazar. Aynı uzman-yanıt çifti ikinci kez yazılamaz."""
        cas_total = sum(payload[item.key] for item in CAS_ITEMS)
        discern_total = sum(payload[item.key] for item in DISCERN_ITEMS)
        with self._session() as session:
            score = Score(
                response_id=payload["response_id"],
                evaluator_id=payload["evaluator_id"],
                gqs=payload["gqs"],
                checklist_json=json.dumps(payload["checklist"], ensure_ascii=False),
                checklist_pct=payload["checklist_pct"],
                checklist_weighted_pct=payload["checklist_weighted_pct"],
                cas_food=payload["cas_food"],
                cas_religion=payload["cas_religion"],
                cas_health_system=payload["cas_health_system"],
                cas_local=payload["cas_local"],
                cas_cultural=payload["cas_cultural"],
                cas_total=cas_total,
                safety_issue=payload["safety_issue"],
                safety_note=payload["safety_note"],
                discern_purpose=payload["discern_purpose"],
                discern_relevance=payload["discern_relevance"],
                discern_sources=payload["discern_sources"],
                discern_uncertainty=payload["discern_uncertainty"],
                discern_alternatives=payload["discern_alternatives"],
                discern_risks=payload["discern_risks"],
                discern_physician_ref=payload["discern_physician_ref"],
                discern_balance=payload["discern_balance"],
                discern_total=discern_total,
                evaluated_at=utc_now(),
            )
            session.add(score)
            session.flush()
            return score.score_id

    def scored_response_ids(self, evaluator_id: str) -> set[int]:
        """Uzmanın puanladığı yanıt kimlikleri."""
        with self._session() as session:
            rows = (
                session.query(Score.response_id)
                .filter(Score.evaluator_id == evaluator_id)
                .all()
            )
            return {row[0] for row in rows}

    def count_for_evaluator(self, evaluator_id: str) -> int:
        """Uzmanın puan sayısı."""
        with self._session() as session:
            return session.query(Score).filter_by(evaluator_id=evaluator_id).count()

    def scored_counts_by_axis(self, evaluator_id: str) -> dict[str, int]:
        """Uzmanın eksen başına puan sayısı."""
        with self._session() as session:
            rows = (
                session.query(Question.axis, Score.score_id)
                .join(Response, Score.response_id == Response.response_id)
                .join(Question, Response.question_id == Question.question_id)
                .filter(Score.evaluator_id == evaluator_id)
                .all()
            )
            counts: dict[str, int] = {}
            for axis, _score_id in rows:
                counts[axis] = counts.get(axis, 0) + 1
            return counts


def _evaluator_dict(evaluator: Evaluator) -> dict:
    """Uzman kaydını şifresiz sözlüğe çevirir."""
    return {
        "evaluator_id": evaluator.evaluator_id,
        "name": evaluator.name,
        "role": evaluator.role,
        "assigned_axes": json.loads(evaluator.assigned_axes),
    }


def _blinded_payload(response: Response, question: Question) -> dict:
    """Puanlama ekranına gidecek, model içermeyen yanıt görünümü."""
    try:
        checklist = json.loads(question.checklist_json or "[]")
    except json.JSONDecodeError:
        checklist = []
    return {
        "response_id": response.response_id,
        "blind_code": response.blind_code,
        "response_text": response.response_text,
        "question_text": question.question_text,
        "axis": question.axis,
        "checklist": checklist,
    }


def _sort_question_ids(records: list[dict]) -> list[dict]:
    """Excel sırasını korur: Q1..Q20, ardından K1..K10."""

    def key(record: dict) -> tuple:
        """Hasta sorularını kılavuz vakalarından önce, kendi içinde sayısal sıralar."""
        raw = record["question_id"]
        prefix = raw[:1]
        number = int(raw[1:]) if raw[1:].isdigit() else 0
        group = 0 if prefix == "Q" else 1
        return (group, number)

    return sorted(records, key=key)
