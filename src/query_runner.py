"""
GDM LLM çalışması sorgu motoru.

Eksik soru-model-tekrar üçlülerini sorgular, yanıtı ve okunabilirliği kaydeder.
Kör kodlar tüm yanıtlar tamamlandıktan sonra ayrı komutla atanır.
"""

import argparse
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from src.database import (
    DATABASE_URL,
    ENGINE,
    PILOT_DB_PATH,
    EvaluatorRepository,
    ModelRepository,
    QuestionRepository,
    ResponseRepository,
    init_db,
    sqlite_engine,
)
from src.domain import QUERY_INTERVAL_SECONDS
from src.llm_clients import ClientFactory, load_model_specs
from src.logging_config import setup_logging
from src.question_importer import EXCEL_FILENAME, import_questions
from src.readability import analyze_text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger("gdm.query")


class StudyRunner:
    """Sorgu, kurulum ve kör kod atamasını repository'ler üzerinden yürütür."""

    def __init__(
        self,
        engine,
        questions: QuestionRepository,
        models: ModelRepository,
        responses: ResponseRepository,
        evaluators: EvaluatorRepository,
        client_factory: ClientFactory,
    ):
        """Bağımlılıklar dışarıdan verilir. engine, tabloların kurulacağı veritabanıdır."""
        self._engine = engine
        self._questions = questions
        self._models = models
        self._responses = responses
        self._evaluators = evaluators
        self._client_factory = client_factory

    def initialize(self) -> None:
        """Excel'den JSON üretir, tabloları kurar, soru, model ve uzmanları yükler."""
        init_db(self._engine)
        json_path = PROJECT_ROOT / "data" / "questions.json"
        payload = import_questions(PROJECT_ROOT / "data" / EXCEL_FILENAME, json_path)
        loaded = self._questions.upsert_from_json(json_path)
        specs = load_model_specs(PROJECT_ROOT / "config" / "models.yaml")
        self._sync_models(specs)
        created = self._evaluators.seed_defaults()
        logger.info("%d soru yüklendi.", loaded)
        logger.info("%d model yüklendi.", len(specs))
        if created:
            print("Yeni uzmanlar eklendi. Şifreler yalnızca bu kez gösterilir:", flush=True)
            for seed in created:
                print(f"  {seed.evaluator_id} ({seed.name}): {seed.password}", flush=True)
        else:
            logger.info("Uzmanlar zaten kayıtlı. Şifreler yeniden gösterilmez.")
        logger.info("Kaynak dosya: %s", payload["source"])

    async def run(self, pilot: bool = False) -> None:
        """Eksik kombinasyonları sorgular. Hata olursa loglar ve devam eder."""
        init_db(self._engine)
        if pilot and self._questions.count() == 0:
            logger.info("Pilot veritabanı boş; kurulum yapılıyor.")
            self.initialize()
        questions = self._questions.list_records()
        specs = load_model_specs(PROJECT_ROOT / "config" / "models.yaml")
        self._sync_models(specs)
        models = self._models.list_records()
        if not questions or not models:
            logger.error("Soru veya model yok. Önce --init çalıştırın.")
            return

        clients = {spec.model_id: client for spec, client in self._client_factory.create_all(specs)}
        repetitions = 1 if pilot else 2
        if pilot:
            questions = questions[:3]
            models = models[:2]
            logger.info("Pilot mod: 3 soru, 2 model, 1 tekrar.")
        else:
            logger.info("Tam mod: %d soru, %d model, 2 tekrar.", len(questions), len(models))

        planned = []
        for question in questions:
            for model in models:
                for repetition in range(1, repetitions + 1):
                    planned.append((question, model, repetition))

        existing = self._responses.existing_keys()
        pending = [
            item
            for item in planned
            if (item[0]["question_id"], item[1]["model_id"], item[2]) not in existing
        ]
        already = len(planned) - len(pending)
        logger.info("Planlanan: %d, kayıtlı: %d, sorgulanacak: %d", len(planned), already, len(pending))

        started = datetime.now(timezone.utc)
        success = 0
        failure = 0
        truncated = 0
        for index, (question, model, repetition) in enumerate(pending, start=1):
            client = clients.get(model["model_id"])
            if client is None:
                failure += 1
                logger.error("İstemci yok: %s", model["model_id"])
            else:
                logger.info(
                    "Sorgu %s | %s | tekrar %d",
                    question["question_id"],
                    model["model_id"],
                    repetition,
                )
                result = await client.query(question["question_text"])
                if result.success:
                    self._store_response(question, model, repetition, result)
                    success += 1
                    if result.truncated:
                        truncated += 1
                    logger.info(
                        "Başarılı. tokens=%s latency_ms=%s finish_reason=%s",
                        result.tokens_used,
                        result.latency_ms,
                        result.finish_reason,
                    )
                else:
                    failure += 1
                    logger.error("Başarısız: %s", result.error_message)

            done = already + success + failure
            logger.info("Progress: %d/%d", done, len(planned))
            if index < len(pending):
                await asyncio.sleep(QUERY_INTERVAL_SECONDS)

        finished = datetime.now(timezone.utc)
        duration = (finished - started).total_seconds()
        logger.info("Başlangıç (UTC): %s", started.isoformat())
        logger.info("Bitiş (UTC): %s", finished.isoformat())
        logger.info("Süre: %.1f saniye", duration)
        logger.info("Bu çalıştırmada başarılı: %d, başarısız: %d", success, failure)
        if truncated:
            logger.warning(
                "%d yanıt belirteç sınırında kesildi. responses.finish_reason alanını inceleyin.",
                truncated,
            )

    def assign_codes(self, seed: int, pilot: bool = False) -> None:
        """Tamamlanmış yanıt kümesine karışık kör kod atar."""
        init_db(self._engine)
        question_count = 3 if pilot else self._questions.count()
        model_count = 2 if pilot else self._models.count()
        repetitions = 1 if pilot else 2
        expected = question_count * model_count * repetitions
        assigned = self._responses.assign_blind_codes(seed, expected)
        logger.info("Kör kod atandı. adet=%d seed=%d", assigned, seed)

    def _store_response(self, question: dict, model: dict, repetition: int, result) -> None:
        """Yanıtı ve okunabilirliği yazar. Kopan pooler bağlantısında bir kez dener."""
        last_error = None
        for attempt in range(2):
            try:
                response_id = self._responses.add(
                    question_id=question["question_id"],
                    model_id=model["model_id"],
                    repetition=repetition,
                    response_text=result.response_text,
                    tokens_used=result.tokens_used,
                    latency_ms=result.latency_ms,
                    model_version_returned=result.model_version_returned,
                    finish_reason=result.finish_reason,
                )
                self._responses.add_readability(response_id, analyze_text(result.response_text))
                return
            except OperationalError as exc:
                last_error = exc
                logger.warning("Veritabanı bağlantısı koptu, yeniden denenecek.")
        raise last_error

    def _sync_models(self, specs) -> None:
        """models.yaml içeriğini veritabanına yazar."""
        self._models.upsert_many(
            [
                {
                    "model_id": spec.model_id,
                    "provider": spec.provider,
                    "model_string": spec.model_string,
                    "temperature": None,
                    "reasoning_effort": spec.reasoning_effort,
                    "system_prompt": spec.system_prompt,
                }
                for spec in specs
            ]
        )


def build_runner(pilot: bool = False) -> StudyRunner:
    """
    Repository'leri ve istemci fabrikasını kurar.

    Pilot mod data/pilot.db kullanır; ana çalışmanın yanıtlarına ve kör kodlarına dokunmaz.
    """
    if pilot:
        if DATABASE_URL:
            raise SystemExit("Pilot mod yalnızca yerel SQLite ile çalışır. DATABASE_URL'i kaldırın.")
        engine = sqlite_engine(PILOT_DB_PATH)
    else:
        engine = ENGINE
    factory = sessionmaker(bind=engine)
    return StudyRunner(
        engine=engine,
        questions=QuestionRepository(factory),
        models=ModelRepository(factory),
        responses=ResponseRepository(factory),
        evaluators=EvaluatorRepository(factory),
        client_factory=ClientFactory(),
    )


def main() -> None:
    """Komut satırı giriş noktası."""
    setup_logging(PROJECT_ROOT / "logs")
    parser = argparse.ArgumentParser(description="GDM LLM çalışması sorgu motoru")
    parser.add_argument("--init", action="store_true", help="Excel, veritabanı, model ve uzman kurulumu")
    parser.add_argument("--run", action="store_true", help="Eksik kombinasyonları sorgula")
    parser.add_argument(
        "--pilot",
        action="store_true",
        help="3 soru, 2 model, 1 tekrar; ayrı data/pilot.db dosyası",
    )
    parser.add_argument("--assign-codes", action="store_true", help="Kör kod ata")
    parser.add_argument("--seed", type=int, help="Kör kod karıştırması için tam sayı")
    args = parser.parse_args()

    selected = sum([args.init, args.run, args.assign_codes])
    if selected != 1:
        parser.error("Şu komutlardan tam olarak birini verin: --init, --run, --assign-codes")
    if args.assign_codes and args.seed is None:
        parser.error("--assign-codes için --seed zorunludur")
    runner = build_runner(pilot=args.pilot)
    if args.init:
        runner.initialize()
    elif args.run:
        asyncio.run(runner.run(pilot=args.pilot))
    else:
        runner.assign_codes(seed=args.seed, pilot=args.pilot)


if __name__ == "__main__":
    main()
