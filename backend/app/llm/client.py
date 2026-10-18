"""OpenAI-compatible LLM client with model fallback.

Works with OpenRouter, Google Gemini (OpenAI endpoint), Ollama, LM Studio, OpenAI itself:
set LLM_BASE_URL, LLM_API_KEY and LLM_MODELS in .env.
"""

import asyncio
import base64
import io
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import TypeVar

from openai import AsyncOpenAI
from PIL import Image
from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.llm.prompt import (
    BANK_SYSTEM,
    PRODUCTS_SYSTEM,
    VOICE_USER,
    localize,
    products_user,
    receipt_text_user,
    receipt_user,
)
from app.llm.schema import ParsedBank, ParsedManual, ParsedProducts, ParsedReceipt, ParsedVoice
from app.llm.usage import record_call

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")

# a long text is cut: the model has a limit too
MAX_RECEIPT_TEXT = 30000
MAX_STATEMENT_TEXT = 60000

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


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

    @staticmethod
    async def _first_success(models: list[str], attempt: Callable[[str], Awaitable[R]]) -> R:
        """Tries the models in order; the first one that answers wins. LLMError lists every failure."""
        errors: list[str] = []
        for model in models:
            try:
                return await attempt(model)
            except (ValueError, ValidationError) as e:
                log.warning("model %s returned a bad answer: %s", model, e)
                errors.append(f"{model}: bad answer ({type(e).__name__})")
            except Exception as e:  # network, rate limit, unsupported model, ...
                log.warning("model %s failed: %s", model, e)
                errors.append(f"{model}: {type(e).__name__}: {str(e)[:200]}")
        raise LLMError("; ".join(errors) or "no models configured")

    async def structured(
        self, messages: list[dict], schema: type[T], models: list[str], task: str = "other"
    ) -> LLMResult[T]:
        async def attempt(model: str) -> LLMResult[T]:
            raw = extract_json(await self._ask(model, messages, task))
            return LLMResult(data=schema.model_validate(raw), model=model, raw=raw)

        return await self._first_success(models, attempt)

    async def parse_receipt(
        self, image: Image.Image, system: str, models: list[str] | None = None, hint: str | None = None
    ):
        url = await asyncio.to_thread(image_to_data_url, image, self.settings.llm_max_image_side)
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": receipt_user(hint)},
                    {"type": "image_url", "image_url": {"url": url}},
                ],
            },
        ]
        return await self.structured(messages, ParsedReceipt, models or self.settings.models, "receipt")

    async def parse_manual(self, text: str, system: str):
        messages = [{"role": "system", "content": system}, {"role": "user", "content": text}]
        return await self.structured(messages, ParsedManual, self.settings.text_models, "manual")

    async def complete_text(self, messages: list[dict], models: list[str], task: str = "comment") -> tuple[str, str]:
        """Plain text answer and the model that gave it."""

        async def attempt(model: str) -> tuple[str, str]:
            text = (await self._ask(model, messages, task)).strip()
            if not text:
                raise LLMError("empty answer")
            return text, model

        return await self._first_success(models, attempt)

    async def parse_receipt_text(
        self, text: str, system: str, hint: str | None = None, models: list[str] | None = None
    ):
        user = receipt_text_user(text[:MAX_RECEIPT_TEXT], hint)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        return await self.structured(messages, ParsedReceipt, models or self.settings.text_models, "receipt_text")

    async def parse_bank(self, text: str):
        messages = [{"role": "system", "content": BANK_SYSTEM}, {"role": "user", "content": text[:MAX_STATEMENT_TEXT]}]
        return await self.structured(messages, ParsedBank, self.settings.text_models, "bank")

    async def parse_voice(self, wav: bytes, system: str):
        models = self.settings.audio_models
        if not models:
            raise LLMError("LLM_AUDIO_MODELS is empty")
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": VOICE_USER},
                    {"type": "input_audio", "input_audio": {"data": base64.b64encode(wav).decode(), "format": "wav"}},
                ],
            },
        ]
        return await self.structured(messages, ParsedVoice, models, "voice")

    async def group_products(self, names: list[str], known: list[str]):
        messages = [
            {"role": "system", "content": localize(PRODUCTS_SYSTEM)},
            {"role": "user", "content": products_user(names, known)},
        ]
        return await self.structured(messages, ParsedProducts, self.settings.text_models, "products")

    async def chat_tools(self, messages: list[dict], tools: list[dict], models: list[str]):
        """One step of a tool-calling conversation: returns (assistant message, model)."""

        async def attempt(model: str):
            resp = await self._create("ask", model, messages=messages, tools=tools)
            if not resp.choices:
                raise LLMError("no choices")
            return resp.choices[0].message, model

        return await self._first_success(models, attempt)


@lru_cache
def get_llm() -> LLMClient:
    """One client for the whole process: it owns a connection pool, so it is not rebuilt per request."""
    return LLMClient()
