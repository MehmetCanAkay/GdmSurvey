"""Arayüzün bağımlılıklarını tek yerde kurar."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.evaluator_service import EvaluatorService
    from app.services.progress_service import ProgressService
    from app.services.response_service import ResponseService
    from app.services.scoring_service import ScoringService


@dataclass
class Services:
    """Sayfaların kullandığı servis demeti."""

    evaluators: EvaluatorService
    responses: ResponseService
    scoring: ScoringService
    progress: ProgressService


_services: Services | None = None


def app_services() -> Services:
    """Arayüz servislerini havuzlu motorla bir kez kurar; tüm oturumlar paylaşır."""
    global _services
    if _services is None:
        from sqlalchemy.orm import sessionmaker

        from src.database import interactive_engine

        _services = build_services(sessionmaker(bind=interactive_engine()))
    return _services


def build_services(session_factory=None) -> Services:
    """Repository'leri ve servisleri oluşturur. Oturum fabrikası değiştirilebilir."""
    from app.services.evaluator_service import EvaluatorService
    from app.services.progress_service import ProgressService
    from app.services.response_service import ResponseService
    from app.services.scoring_service import ScoringService
    from src.database import (
        EvaluatorRepository,
        ResponseRepository,
        ScoreRepository,
        SessionLocal,
    )

    factory = session_factory or SessionLocal
    evaluators = EvaluatorRepository(factory)
    responses = ResponseRepository(factory)
    scores = ScoreRepository(factory)
    return Services(
        evaluators=EvaluatorService(evaluators),
        responses=ResponseService(responses, scores, evaluators),
        scoring=ScoringService(scores),
        progress=ProgressService(responses, scores, evaluators),
    )
