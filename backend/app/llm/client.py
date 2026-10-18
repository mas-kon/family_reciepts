"""OpenAI-compatible LLM client with model fallback.

Works with OpenRouter, Google Gemini (OpenAI endpoint), Ollama, LM Studio, OpenAI itself:
set LLM_BASE_URL, LLM_API_KEY and LLM_MODELS in .env.
"""

import base64
import io
import json
import logging
import re
from dataclasses import dataclass
from typing import TypeVar

from openai import AsyncOpenAI
from PIL import Image
from pydantic import BaseModel, ValidationError

from app.config import get_settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


class LLMError(Exception):
    pass


@dataclass
class LLMResult[T]:
    data: T
    model: str
    raw: dict


def extract_json(text: str) -> dict:
    """Pull a JSON object out of a model answer that may contain fences or chatter."""
    if not text:
        raise ValueError("empty answer")
    m = _FENCE.search(text)
    if m:
        text = m.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in answer")
    return json.loads(text[start : end + 1])


def image_to_data_url(image: Image.Image, max_side: int) -> str:
    img = image.convert("RGB")  # callers pass EXIF-transposed images
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


class LLMClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        s = get_settings()
        self.settings = s
        self.client = AsyncOpenAI(
            base_url=base_url or s.llm_base_url,
            api_key=api_key or s.llm_api_key or "none",
            timeout=s.llm_timeout,
            max_retries=1,
            default_headers={"X-Title": "check-bot"},
        )

    async def _create(self, task: str, model: str, **kwargs):
        """One request; every attempt, failed or not, goes to the usage log (app.llm.usage)."""
        from app.llm.usage import record_call

        try:
            resp = await self.client.chat.completions.create(model=model, temperature=0, **kwargs)
        except Exception as e:
            await record_call(task, model, None, error=e)
            raise
        await record_call(task, model, resp)
        return resp

    async def _ask(self, model: str, messages: list[dict], task: str = "other") -> str:
        resp = await self._create(task, model, messages=messages)
        if not resp.choices:
            raise LLMError("no choices in response")
        return resp.choices[0].message.content or ""

    async def structured(
        self, messages: list[dict], schema: type[T], models: list[str], task: str = "other"
    ) -> LLMResult[T]:
        errors: list[str] = []
        for model in models:
            try:
                text = await self._ask(model, messages, task)
                raw = extract_json(text)
                return LLMResult(data=schema.model_validate(raw), model=model, raw=raw)
            except (ValueError, ValidationError) as e:
                log.warning("model %s returned bad JSON: %s", model, e)
                errors.append(f"{model}: bad answer ({type(e).__name__})")
            except Exception as e:  # network, rate limit, unsupported model, ...
                log.warning("model %s failed: %s", model, e)
                errors.append(f"{model}: {type(e).__name__}: {str(e)[:200]}")
        raise LLMError("; ".join(errors) or "no models configured")

    async def parse_receipt(
        self, image: Image.Image, system: str, models: list[str] | None = None, hint: str | None = None
    ):
        from app.llm.prompt import RECEIPT_USER
        from app.llm.schema import ParsedReceipt

        url = image_to_data_url(image, self.settings.llm_max_image_side)
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": RECEIPT_USER + (f"\nПодпись пользователя к чеку: {hint}" if hint else "")},
                    {"type": "image_url", "image_url": {"url": url}},
                ],
            },
        ]
        return await self.structured(messages, ParsedReceipt, models or self.settings.models, "receipt")

    async def parse_manual(self, text: str, system: str):
        from app.llm.schema import ParsedManual

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ]
        return await self.structured(messages, ParsedManual, self.settings.text_models, "manual")

    # ---------- free text ----------

    async def complete_text(self, messages: list[dict], models: list[str], task: str = "comment") -> tuple[str, str]:
        """Plain text answer and the model that gave it."""
        errors: list[str] = []
        for model in models:
            try:
                text = (await self._ask(model, messages, task)).strip()
                if text:
                    return text, model
                errors.append(f"{model}: empty answer")
            except Exception as e:
                log.warning("model %s failed: %s", model, e)
                errors.append(f"{model}: {type(e).__name__}: {str(e)[:200]}")
        raise LLMError("; ".join(errors) or "no models configured")

    # ---------- receipts as text (e-mail) ----------

    async def parse_receipt_text(
        self, text: str, system: str, hint: str | None = None, models: list[str] | None = None
    ):
        from app.llm.prompt import RECEIPT_TEXT_USER
        from app.llm.schema import ParsedReceipt

        user = RECEIPT_TEXT_USER + (f"Подпись пользователя: {hint}\n\n" if hint else "") + text[:30000]
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        return await self.structured(messages, ParsedReceipt, models or self.settings.text_models, "receipt_text")

    # ---------- bank ----------

    async def parse_bank(self, text: str):
        from app.llm.prompt import BANK_SYSTEM
        from app.llm.schema import ParsedBank

        messages = [{"role": "system", "content": BANK_SYSTEM}, {"role": "user", "content": text[:60000]}]
        return await self.structured(messages, ParsedBank, self.settings.text_models, "bank")

    # ---------- voice ----------

    async def parse_voice(self, wav: bytes, system: str):
        from app.llm.schema import ParsedVoice

        models = self.settings.audio_models
        if not models:
            raise LLMError("LLM_AUDIO_MODELS is empty")
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Запиши трату из этого голосового сообщения."},
                    {"type": "input_audio", "input_audio": {"data": base64.b64encode(wav).decode(), "format": "wav"}},
                ],
            },
        ]
        return await self.structured(messages, ParsedVoice, models, "voice")

    # ---------- products ----------

    async def group_products(self, names: list[str], known: list[str]):
        from app.llm.prompt import PRODUCTS_SYSTEM
        from app.llm.schema import ParsedProducts

        user = (
            "Известные товары:\n" + ("\n".join(f"- {k}" for k in known) or "(пока нет)")
            + "\n\nНовые названия из чеков:\n" + "\n".join(f"- {n}" for n in names)
        )
        messages = [{"role": "system", "content": PRODUCTS_SYSTEM}, {"role": "user", "content": user}]
        return await self.structured(messages, ParsedProducts, self.settings.text_models, "products")

    # ---------- tool calling (questions in the web UI) ----------

    async def chat_tools(self, messages: list[dict], tools: list[dict], models: list[str]):
        """One step of a tool-calling conversation: returns (assistant message, model)."""
        errors: list[str] = []
        for model in models:
            try:
                resp = await self._create("ask", model, messages=messages, tools=tools)
                if resp.choices:
                    return resp.choices[0].message, model
                errors.append(f"{model}: no choices")
            except Exception as e:
                log.warning("model %s failed: %s", model, e)
                errors.append(f"{model}: {type(e).__name__}: {str(e)[:200]}")
        raise LLMError("; ".join(errors) or "no models configured")
