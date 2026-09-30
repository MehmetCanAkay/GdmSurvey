"""
Dil modeli istemcileri.

Her sağlayıcı aynı sözleşmeyi uygular: temperature gönderilmez (sağlayıcı varsayılanı),
system prompt yoktur, düşünme seviyesi models.yaml'dan sabit okunur.
Zaman aşımı ve yalnızca geçici hatalarda üç deneme uygulanır.
API anahtarları ortam değişkeninden okunur ve loglara yazılmaz.
"""

import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from src.domain import ALLOWED_REASONING_EFFORTS, MAX_OUTPUT_TOKENS, REQUEST_TIMEOUT_SECONDS

logger = logging.getLogger("gdm.llm")

# Yanıtın sınırda kesildiğini gösteren bitiş nedenleri.
TRUNCATION_REASONS = frozenset({"max_tokens", "max_output_tokens", "length", "MAX_TOKENS"})


@dataclass
class LLMResponse:
    """Bir model çağrısının sonucu."""

    response_text: str
    tokens_used: int
    latency_ms: int
    model_version_returned: str
    finish_reason: str | None = None
    success: bool = True
    error_message: str | None = None

    @property
    def truncated(self) -> bool:
        """Yanıt belirteç sınırında kesildiyse True döner."""
        return self.finish_reason in TRUNCATION_REASONS


@dataclass(frozen=True)
class ModelSpec:
    """YAML'den okunan ve veritabanına yazılan model tanımı."""

    model_id: str
    provider: str
    model_string: str
    reasoning_effort: str | None
    system_prompt: str | None = None


class LLMClient(Protocol):
    """Sorgu motorunun gördüğü model sözleşmesi."""

    provider: str
    model_string: str

    async def query(self, question: str) -> LLMResponse:
        """Hastanın sorusunu, system prompt olmadan gönderir."""


def load_model_specs(yaml_path: Path) -> list[ModelSpec]:
    """
    Model yapılandırmasını okur ve çalışma kurallarını denetler.

    temperature tanımlıysa veya system prompt doluysa çalışma başlamaz.
    Düşünme seviyesi sağlayıcının kabul ettiği değerlerden biri olmalıdır.
    """
    with Path(yaml_path).open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    specs: list[ModelSpec] = []
    for item in config["models"]:
        model_id = item["model_id"]
        provider = item["provider"]
        if item.get("temperature") is not None:
            raise ValueError(
                f"{model_id}: temperature tanımlanmamalı. Güncel modeller bu parametreyi reddeder; "
                "örnekleme sağlayıcı varsayılanında kalır."
            )
        if item.get("system_prompt") not in (None, ""):
            raise ValueError(f"{model_id}: system prompt boş olmalıdır.")
        if provider not in ALLOWED_REASONING_EFFORTS:
            known = ", ".join(ALLOWED_REASONING_EFFORTS)
            raise ValueError(f"{model_id}: bilinmeyen sağlayıcı {provider}. Bilinenler: {known}")
        effort = item.get("reasoning_effort")
        allowed = ALLOWED_REASONING_EFFORTS[provider]
        if allowed and effort not in allowed:
            options = ", ".join(sorted(allowed))
            raise ValueError(f"{model_id}: reasoning_effort {effort!r} geçersiz. Seçenekler: {options}")
        if not allowed and effort is not None:
            raise ValueError(f"{model_id}: {provider} için reasoning_effort boş bırakılmalıdır.")
        specs.append(
            ModelSpec(
                model_id=model_id,
                provider=provider,
                model_string=item["model_string"],
                reasoning_effort=effort,
            )
        )
    return specs


class ClientFactory:
    """Model tanımından somut istemci üretir."""

    def __init__(self, env: dict[str, str] | None = None):
        """Anahtarlar varsayılan olarak süreç ortamından okunur."""
        self._env = env if env is not None else os.environ

    def create(self, spec: ModelSpec) -> LLMClient:
        """Sağlayıcı adına göre istemci sınıfını seçer."""
        mapping = {
            "OpenAI": OpenAIClient,
            "Anthropic": AnthropicClient,
            "Google": GeminiClient,
            "Yerli": LocalModelClient,
        }
        client_type = mapping.get(spec.provider)
        if client_type is None:
            known = ", ".join(mapping)
            raise ValueError(f"Bilinmeyen sağlayıcı: {spec.provider}. Bilinenler: {known}")
        return client_type(spec.model_string, spec.reasoning_effort, self._env)

    def create_all(self, specs: list[ModelSpec]) -> list[tuple[ModelSpec, LLMClient]]:
        """Tüm modeller için istemci listesi kurar."""
        return [(spec, self.create(spec)) for spec in specs]


class _BaseClient:
    """Ortak kurucu, gösterim ve yeniden deneme sarmalayıcısı."""

    provider = ""

    def __init__(self, model_string: str, reasoning_effort: str | None, env: dict[str, str]):
        """Model kimliğini, düşünme seviyesini ve ortam sözlüğünü saklar. Ağa bağlanmaz."""
        self.model_string = model_string
        self.reasoning_effort = reasoning_effort
        self._env = env

    def __repr__(self) -> str:
        """Anahtar ve adres içermeyen kısa gösterim."""
        return f"{type(self).__name__}(model_string={self.model_string!r})"

    async def query(self, question: str) -> LLMResponse:
        """Soruyu gönderir. Kalıcı hatalar yeniden denenmez; hata sonucu döner."""
        try:
            result = await _call_with_retry(self._once, question)
        except Exception as exc:
            return _failed(self.provider, self.model_string, exc)
        if result.truncated:
            logger.warning(
                "Yanıt belirteç sınırında kesildi. provider=%s model=%s finish_reason=%s",
                self.provider,
                self.model_string,
                result.finish_reason,
            )
        return result

    async def _once(self, question: str) -> LLMResponse:
        """Tek bir sağlayıcı çağrısı. Alt sınıflar uygular."""
        raise NotImplementedError


class OpenAIClient(_BaseClient):
    """OpenAI Responses API. instructions ve temperature gönderilmez."""

    provider = "OpenAI"

    async def _once(self, question: str) -> LLMResponse:
        """Tek bir OpenAI çağrısı yapar."""
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=_required(self._env, "OPENAI_API_KEY"),
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        )
        started = time.perf_counter()
        response = await client.responses.create(
            model=self.model_string,
            input=question,
            reasoning={"effort": self.reasoning_effort},
            max_output_tokens=MAX_OUTPUT_TOKENS,
            store=False,
        )
        finish = response.status
        if response.incomplete_details is not None and response.incomplete_details.reason:
            finish = response.incomplete_details.reason
        return _success(
            text=response.output_text or "",
            tokens=response.usage.total_tokens if response.usage else 0,
            started=started,
            version=response.model or self.model_string,
            finish_reason=finish,
        )


class AnthropicClient(_BaseClient):
    """Anthropic Messages API. system, thinking ve temperature gönderilmez."""

    provider = "Anthropic"

    async def _once(self, question: str) -> LLMResponse:
        """Tek bir Anthropic çağrısı yapar. Düşünme blokları yanıt metnine alınmaz."""
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(
            api_key=_required(self._env, "ANTHROPIC_API_KEY"),
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        )
        started = time.perf_counter()
        response = await client.messages.create(
            model=self.model_string,
            max_tokens=MAX_OUTPUT_TOKENS,
            messages=[{"role": "user", "content": question}],
            output_config={"effort": self.reasoning_effort},
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        tokens = 0
        if response.usage:
            tokens = response.usage.input_tokens + response.usage.output_tokens
        return _success(
            text=text,
            tokens=tokens,
            started=started,
            version=response.model or self.model_string,
            finish_reason=response.stop_reason,
        )


class GeminiClient(_BaseClient):
    """Google Gemini, google-genai paketi. system instruction ve temperature verilmez."""

    provider = "Google"

    async def _once(self, question: str) -> LLMResponse:
        """Tek bir Gemini çağrısı yapar."""
        from google import genai
        from google.genai import types

        client = genai.Client(
            api_key=_required(self._env, "GOOGLE_API_KEY"),
            http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_SECONDS * 1000),
        )
        started = time.perf_counter()
        response = await client.aio.models.generate_content(
            model=self.model_string,
            contents=question,
            config=types.GenerateContentConfig(
                max_output_tokens=MAX_OUTPUT_TOKENS,
                thinking_config=types.ThinkingConfig(
                    thinking_level=types.ThinkingLevel(self.reasoning_effort.upper()),
                ),
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
        usage = response.usage_metadata
        tokens = 0
        if usage is not None:
            tokens = usage.total_token_count or (
                (usage.prompt_token_count or 0)
                + (usage.candidates_token_count or 0)
                + (usage.thoughts_token_count or 0)
            )
        finish = None
        if response.candidates:
            reason = response.candidates[0].finish_reason
            finish = getattr(reason, "value", reason)
        return _success(
            text=response.text or "",
            tokens=int(tokens),
            started=started,
            version=response.model_version or self.model_string,
            finish_reason=finish,
        )


class LocalModelClient(_BaseClient):
    """
    Yerli model için OpenAI uyumlu HTTP uç noktası (mlx_lm.server). temperature gönderilmez.

    Örnekleme ayarları sunucu başlatılırken modelin generation_config.json değerleriyle verilir.
    Düşünme bloğu uzmanlara gösterilmemesi için yanıt metninden ayıklanır.
    """

    provider = "Yerli"

    async def _once(self, question: str) -> LLMResponse:
        """Tek bir yerel model çağrısı yapar."""
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            base_url=self._env.get("LOCAL_MODEL_ENDPOINT", "http://localhost:8080/v1"),
            api_key=self._env.get("LOCAL_MODEL_API_KEY", "not-needed"),
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        )
        started = time.perf_counter()
        response = await client.chat.completions.create(
            model=self.model_string,
            messages=[{"role": "user", "content": question}],
            max_tokens=MAX_OUTPUT_TOKENS,
        )
        choice = response.choices[0]
        return _success(
            text=_strip_thinking(choice.message.content or ""),
            tokens=response.usage.total_tokens if response.usage else 0,
            started=started,
            version=response.model or self.model_string,
            finish_reason=choice.finish_reason,
        )


def _strip_thinking(text: str) -> str:
    """
    <think>…</think> düşünme bloğunu yanıttan siler.

    Sohbet şablonu <think> etiketini istemin içinde açtığında metinde yalnızca
    </think> görünür; öncesi düşünmedir. Kapanmamış <think> ise yanıtın düşünme
    sırasında kesildiğini gösterir ve geriye nihai yanıt kalmaz.
    """
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    elif "<think>" in text:
        text = text.split("<think>", 1)[0]
    return text.strip()


def _required(env: dict[str, str], name: str) -> str:
    """Zorunlu ortam değişkenini okur. Değeri loglamaz."""
    value = env.get(name)
    if not value:
        raise RuntimeError(f"{name} tanımlı değil. Değeri .env dosyasına yazın.")
    return value


def _success(
    text: str,
    tokens: int,
    started: float,
    version: str,
    finish_reason: str | None,
) -> LLMResponse:
    """Ölçülmüş başarılı çağrı sonucunu paketler."""
    latency_ms = int((time.perf_counter() - started) * 1000)
    return LLMResponse(
        response_text=text,
        tokens_used=tokens,
        latency_ms=latency_ms,
        model_version_returned=version,
        finish_reason=None if finish_reason is None else str(finish_reason),
        success=True,
    )


def _failed(provider: str, model_string: str, exc: Exception) -> LLMResponse:
    """Başarısız çağrıyı, anahtar içermeyen kısa bir mesajla döndürür."""
    message = _safe_error(exc)
    logger.error(
        "LLM çağrısı başarısız. provider=%s model=%s hata=%s",
        provider,
        model_string,
        message,
    )
    return LLMResponse(
        response_text="",
        tokens_used=0,
        latency_ms=0,
        model_version_returned=model_string,
        success=False,
        error_message=message,
    )


def _safe_error(exc: Exception) -> str:
    """Hata metninden anahtar benzeri dizgileri siler."""
    text = f"{type(exc).__name__}: {exc}"
    text = re.sub(r"sk-[A-Za-z0-9_\-]+", "[GIZLI]", text)
    text = re.sub(r"AIza[0-9A-Za-z_\-]+", "[GIZLI]", text)
    text = re.sub(r"\bAQ\.[0-9A-Za-z_\-.]+", "[GIZLI]", text)
    text = re.sub(r"(?i)(api[_-]?key|key|token|authorization)\s*[:=]\s*[^\s&\"']+", r"\1=[GIZLI]", text)
    return text[:500]


def _is_transient(exc: BaseException) -> bool:
    """
    Yeniden denenecek hataları seçer.

    Kimlik doğrulama ve hatalı istek (400, 401, 403, 404) kalıcıdır.
    Zaman aşımı, hız sınırı ve 5xx geçicidir.
    """
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if not isinstance(status, int):
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    if status in {400, 401, 403, 404}:
        return False
    if status in {408, 409, 429, 500, 502, 503, 504, 529}:
        return True
    name = type(exc).__name__.casefold()
    transient_names = ("timeout", "ratelimit", "rate_limit", "connection", "unavailable", "overloaded")
    if any(token in name for token in transient_names):
        return True
    return isinstance(exc, (TimeoutError, ConnectionError))


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception(_is_transient),
    reraise=True,
)
async def _call_with_retry(func, question: str) -> LLMResponse:
    """Geçici hatalarda aynı çağrıyı en fazla üç kez dener."""
    return await func(question)
