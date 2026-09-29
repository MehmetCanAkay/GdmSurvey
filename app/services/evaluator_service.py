"""Uzman girişi ve listeleme."""

from src.database import EvaluatorRepository


class EvaluatorService:
    """Kimlik doğrulamayı repository üzerinden yürütür."""

    def __init__(self, evaluators: EvaluatorRepository):
        """Uzman repository'sini dışarıdan alır."""
        self._evaluators = evaluators

    def list_for_login(self) -> list[dict]:
        """Giriş listesinde gösterilecek uzmanları döndürür."""
        return self._evaluators.list_all()

    def authenticate(self, username: str, password: str) -> dict | None:
        """Kullanıcı adı ve şifre doğruysa uzman kaydını döndürür."""
        return self._evaluators.authenticate(username, password)
