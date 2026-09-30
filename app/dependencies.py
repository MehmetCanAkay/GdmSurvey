"""Arayüzün bağımlılıklarını tek yerde kurar."""

from dataclasses import dataclass

import streamlit as st
from sqlalchemy.orm import sessionmaker

from app.services.evaluator_service import EvaluatorService
from app.services.progress_service import ProgressService
from app.services.response_service import ResponseService
from app.services.scoring_service import ScoringService
from src.database import (
    EvaluatorRepository,
    ResponseRepository,
    ScoreRepository,
    SessionLocal,
    interactive_engine,
)


@dataclass
class Services:
    """Sayfaların kullandığı servis demeti."""

    evaluators: EvaluatorService
    responses: ResponseService
    scoring: ScoringService
    progress: ProgressService


def build_services(session_factory=None) -> Services:
    """Repository'leri ve servisleri oluşturur. Oturum fabrikası değiştirilebilir."""
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


@st.cache_resource(show_spinner=False)
def app_services() -> Services:
    """Arayüz servislerini havuzlu motorla bir kez kurar; tüm oturumlar paylaşır."""
    return build_services(sessionmaker(bind=interactive_engine()))
