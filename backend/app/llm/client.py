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

    async def _ask(self, model: str, messages: list[dict]) -> str:
        resp = await self.client.chat.completions.create(
            model=model, messages=messages, temperature=0
        )
        if not resp.choices:
            raise LLMError("no choices in response")
        return resp.choices[0].message.content or ""

    async def structured(
        self, messages: list[dict], schema: type[T], models: list[str]
    ) -> LLMResult[T]:
        errors: list[str] = []
        for model in models:
            try:
                text = await self._ask(model, messages)
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
        return await self.structured(messages, ParsedReceipt, models or self.settings.models)

    async def parse_manual(self, text: str, system: str):
        from app.llm.schema import ParsedManual

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ]
        return await self.structured(messages, ParsedManual, self.settings.text_models)
