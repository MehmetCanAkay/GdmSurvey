"""İstemcilerin sağlayıcıya gönderdiği gövde ve model yapılandırması kuralları."""

import asyncio
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from src.domain import MAX_OUTPUT_TOKENS
from src.llm_clients import (
    AnthropicClient,
    GeminiClient,
    LocalModelClient,
    OpenAIClient,
    _is_transient,
    _safe_error,
    _strip_thinking,
    load_model_specs,
)

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN_KEYS = {"temperature", "top_p", "top_k", "system", "instructions", "system_instruction"}


class ModelConfigTests(unittest.TestCase):
    """models.yaml doğrulaması."""

    def test_project_config_is_valid(self) -> None:
        """Depodaki yapılandırma kurallara uyar ve düşünme seviyesi eşittir."""
        specs = load_model_specs(ROOT / "config" / "models.yaml")
        self.assertEqual([spec.model_id for spec in specs], ["M1", "M2", "M3", "M4"])
        efforts = {spec.reasoning_effort for spec in specs if spec.provider != "Yerli"}
        self.assertEqual(efforts, {"medium"})

    def test_temperature_is_rejected(self) -> None:
        """temperature yazılırsa çalışma başlamaz."""
        path = _yaml(
            "models:\n"
            "  - {model_id: M1, provider: OpenAI, model_string: x, reasoning_effort: medium, temperature: 0}\n"
        )
        with self.assertRaises(ValueError):
            load_model_specs(path)

    def test_system_prompt_is_rejected(self) -> None:
        """Dolu system prompt çalışmayı durdurur."""
        path = _yaml(
            "models:\n"
            "  - {model_id: M1, provider: OpenAI, model_string: x, reasoning_effort: medium, system_prompt: hi}\n"
        )
        with self.assertRaises(ValueError):
            load_model_specs(path)

    def test_unsupported_effort_is_rejected(self) -> None:
        """Gemini 3.8 Flash 'minimal' kabul etmez."""
        path = _yaml(
            "models:\n"
            "  - {model_id: M3, provider: Google, model_string: x, reasoning_effort: minimal}\n"
        )
        with self.assertRaises(ValueError):
            load_model_specs(path)


class RequestBodyTests(unittest.TestCase):
    """Sahte SDK ile gönderilen parametreleri yakalar."""

    def test_openai_body(self) -> None:
        """Responses API: yalnızca input, sabit effort, temperature ve instructions yok."""
        captured = {}

        class FakeResponses:
            """responses.create çağrısını kaydeder."""

            async def create(self, **kwargs):
                """Gelen parametreleri saklar ve sahte yanıt döndürür."""
                captured.update(kwargs)
                return types.SimpleNamespace(
                    output_text="Yanıt.",
                    usage=types.SimpleNamespace(total_tokens=42),
                    model="gpt-6-astra",
                    status="completed",
                    incomplete_details=None,
                )

        class FakeClient:
            """AsyncOpenAI yerine geçer."""

            def __init__(self, **_kwargs):
                """responses özelliğini kurar."""
                self.responses = FakeResponses()

        with mock.patch("openai.AsyncOpenAI", FakeClient):
            client = OpenAIClient("gpt-6-astra", "medium", {"OPENAI_API_KEY": "test"})
            result = asyncio.run(client.query("Soru?"))
        self.assertTrue(result.success)
        self.assertEqual(captured["input"], "Soru?")
        self.assertEqual(captured["reasoning"], {"effort": "medium"})
        self.assertEqual(captured["max_output_tokens"], MAX_OUTPUT_TOKENS)
        self.assertFalse(FORBIDDEN_KEYS & set(captured))
        self.assertEqual(result.finish_reason, "completed")

    def test_openai_incomplete_is_marked_truncated(self) -> None:
        """Belirteç sınırında kalan yanıt kesik olarak işaretlenir."""

        class FakeResponses:
            """Eksik yanıt döndürür."""

            async def create(self, **_kwargs):
                """Sınıra takılmış yanıt üretir."""
                return types.SimpleNamespace(
                    output_text="Yarım",
                    usage=None,
                    model="gpt-6-astra",
                    status="incomplete",
                    incomplete_details=types.SimpleNamespace(reason="max_output_tokens"),
                )

        class FakeClient:
            """AsyncOpenAI yerine geçer."""

            def __init__(self, **_kwargs):
                """responses özelliğini kurar."""
                self.responses = FakeResponses()

        with mock.patch("openai.AsyncOpenAI", FakeClient):
            client = OpenAIClient("gpt-6-astra", "medium", {"OPENAI_API_KEY": "test"})
            result = asyncio.run(client.query("Soru?"))
        self.assertTrue(result.truncated)

    def test_anthropic_body(self) -> None:
        """Messages API: effort output_config içinde, system ve temperature yok, düşünme metni atılır."""
        captured = {}

        class FakeMessages:
            """messages.create çağrısını kaydeder."""

            async def create(self, **kwargs):
                """Gelen parametreleri saklar ve sahte yanıt döndürür."""
                captured.update(kwargs)
                return types.SimpleNamespace(
                    content=[
                        types.SimpleNamespace(type="thinking", thinking="iç düşünce"),
                        types.SimpleNamespace(type="text", text="Yanıt."),
                    ],
                    usage=types.SimpleNamespace(input_tokens=10, output_tokens=20),
                    model="claude-opus-5-5",
                    stop_reason="end_turn",
                )

        class FakeClient:
            """AsyncAnthropic yerine geçer."""

            def __init__(self, **_kwargs):
                """messages özelliğini kurar."""
                self.messages = FakeMessages()

        with mock.patch("anthropic.AsyncAnthropic", FakeClient):
            client = AnthropicClient("claude-opus-5-5", "medium", {"ANTHROPIC_API_KEY": "test"})
            result = asyncio.run(client.query("Soru?"))
        self.assertEqual(result.response_text, "Yanıt.")
        self.assertEqual(result.tokens_used, 30)
        self.assertEqual(captured["output_config"], {"effort": "medium"})
        self.assertEqual(captured["messages"], [{"role": "user", "content": "Soru?"}])
        self.assertFalse(FORBIDDEN_KEYS & set(captured))
        self.assertNotIn("thinking", captured)

    def test_gemini_body(self) -> None:
        """generateContent: thinking_level sabit, temperature ve system instruction yok."""
        from google.genai import types as genai_types

        captured = {}

        class FakeModels:
            """aio.models.generate_content çağrısını kaydeder."""

            async def generate_content(self, **kwargs):
                """Gelen parametreleri saklar ve sahte yanıt döndürür."""
                captured.update(kwargs)
                return types.SimpleNamespace(
                    text="Yanıt.",
                    usage_metadata=types.SimpleNamespace(
                        total_token_count=50,
                        prompt_token_count=5,
                        candidates_token_count=20,
                        thoughts_token_count=25,
                    ),
                    candidates=[types.SimpleNamespace(finish_reason=genai_types.FinishReason.STOP)],
                    model_version="gemini-3.8-flash",
                )

        class FakeClient:
            """genai.Client yerine geçer."""

            def __init__(self, **_kwargs):
                """aio.models zincirini kurar."""
                self.aio = types.SimpleNamespace(models=FakeModels())

        with mock.patch("google.genai.Client", FakeClient):
            client = GeminiClient("gemini-3.8-flash", "medium", {"GOOGLE_API_KEY": "test"})
            result = asyncio.run(client.query("Soru?"))
        config = captured["config"]
        self.assertTrue(result.success, result.error_message)
        self.assertEqual(captured["contents"], "Soru?")
        self.assertIsNone(config.temperature)
        self.assertIsNone(config.system_instruction)
        self.assertEqual(config.thinking_config.thinking_level, genai_types.ThinkingLevel.MEDIUM)
        self.assertEqual(config.max_output_tokens, MAX_OUTPUT_TOKENS)
        self.assertEqual(result.finish_reason, "STOP")

    def test_local_body(self) -> None:
        """Yerel sunucu: yalnızca kullanıcı mesajı, temperature yok, düşünme bloğu atılır."""
        captured = {}

        class FakeCompletions:
            """chat.completions.create çağrısını kaydeder."""

            async def create(self, **kwargs):
                """Gelen parametreleri saklar ve sahte yanıt döndürür."""
                captured.update(kwargs)
                return types.SimpleNamespace(
                    choices=[
                        types.SimpleNamespace(
                            message=types.SimpleNamespace(content="<think>iç düşünce</think>\n\nYanıt."),
                            finish_reason="stop",
                        )
                    ],
                    usage=types.SimpleNamespace(total_tokens=64),
                    model="models/trendyol-llm-8b-t1-1aeda72-bf16",
                )

        class FakeClient:
            """AsyncOpenAI yerine geçer."""

            def __init__(self, **kwargs):
                """Uç noktayı kaydeder ve chat.completions zincirini kurar."""
                captured["base_url"] = kwargs["base_url"]
                self.chat = types.SimpleNamespace(completions=FakeCompletions())

        with mock.patch("openai.AsyncOpenAI", FakeClient):
            client = LocalModelClient("models/trendyol-llm-8b-t1-1aeda72-bf16", None, {})
            result = asyncio.run(client.query("Soru?"))
        self.assertTrue(result.success, result.error_message)
        self.assertEqual(result.response_text, "Yanıt.")
        self.assertEqual(captured["base_url"], "http://localhost:8080/v1")
        self.assertEqual(captured["messages"], [{"role": "user", "content": "Soru?"}])
        self.assertEqual(captured["max_tokens"], MAX_OUTPUT_TOKENS)
        self.assertFalse(FORBIDDEN_KEYS & set(captured))
        self.assertEqual(result.model_version_returned, "models/trendyol-llm-8b-t1-1aeda72-bf16")

    def test_strip_thinking_variants(self) -> None:
        """Tam blok, yalnızca kapanış etiketi ve kesik düşünme doğru ayıklanır."""
        self.assertEqual(_strip_thinking("<think>a</think>Yanıt."), "Yanıt.")
        self.assertEqual(_strip_thinking("düşünce\n</think>\n\nYanıt."), "Yanıt.")
        self.assertEqual(_strip_thinking("<think>yarım kalan düşünce"), "")
        self.assertEqual(_strip_thinking("Düz yanıt."), "Düz yanıt.")

    def test_missing_key_fails_without_retry(self) -> None:
        """Anahtar yoksa çağrı başarısız döner; hata metninde anahtar geçmez."""
        client = OpenAIClient("gpt-6-astra", "medium", {})
        result = asyncio.run(client.query("Soru?"))
        self.assertFalse(result.success)
        self.assertIn("OPENAI_API_KEY", result.error_message)

    def test_auth_errors_are_not_retried(self) -> None:
        """401 kalıcıdır, 429 geçicidir."""
        auth = type("AuthenticationError", (Exception,), {"status_code": 401})()
        rate = type("RateLimitError", (Exception,), {"status_code": 429})()
        self.assertFalse(_is_transient(auth))
        self.assertTrue(_is_transient(rate))

    def test_error_text_hides_keys(self) -> None:
        """Eski ve yeni Google anahtar biçimleri ile URL içindeki key parametresi gizlenir."""
        message = (
            "istek başarısız: https://x.googleapis.com/v1?key=AQ.Ab8RN6-abc_def "
            "AIzaSyA1234567 sk-proj-abc123 AQ.Zz9-yy"
        )
        text = _safe_error(RuntimeError(message))
        for secret in ("AQ.Ab8RN6", "AIzaSyA", "sk-proj-abc", "AQ.Zz9"):
            self.assertNotIn(secret, text)


def _yaml(text: str) -> Path:
    """Geçici YAML dosyası yazar."""
    handle = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8")
    handle.write(text)
    handle.close()
    return Path(handle.name)


if __name__ == "__main__":
    unittest.main()
