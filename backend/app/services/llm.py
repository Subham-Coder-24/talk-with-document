"""Azure OpenAI client wrapper."""

from __future__ import annotations

import base64
import mimetypes
from collections.abc import AsyncIterator
from pathlib import Path

from openai import AsyncAzureOpenAI, AsyncOpenAI

from app.config import settings

_client: AsyncOpenAI | AsyncAzureOpenAI | None = None


def client() -> AsyncOpenAI | AsyncAzureOpenAI:
    """Supports both Azure endpoint styles:

    - v1 API:     https://<res>.openai.azure.com/openai/v1  -> standard OpenAI client, no api-version
    - classic:    https://<res>.openai.azure.com            -> AzureOpenAI client with api-version
    In both cases `model` is the Azure *deployment* name.
    """
    global _client
    if _client is None:
        endpoint = settings.azure_openai_endpoint.rstrip("/")
        if endpoint.endswith("/openai/v1"):
            _client = AsyncOpenAI(
                base_url=endpoint + "/",
                api_key=settings.azure_openai_api_key,
                timeout=120,
                max_retries=3,
            )
        else:
            _client = AsyncAzureOpenAI(
                azure_endpoint=endpoint,
                api_key=settings.azure_openai_api_key,
                api_version=settings.azure_openai_api_version,
                timeout=120,
                max_retries=3,
            )
    return _client


async def complete(messages: list[dict], temperature: float = 0.0, max_tokens: int = 512) -> str:
    resp = await client().chat.completions.create(
        model=settings.azure_openai_deployment,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()


async def stream(
    messages: list[dict], temperature: float = 0.2, max_tokens: int = 1500
) -> AsyncIterator[str]:
    response = await client().chat.completions.create(
        model=settings.azure_openai_deployment,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )
    async for event in response:
        # Azure sends an initial chunk with prompt-filter results and no choices.
        if not event.choices:
            continue
        delta = event.choices[0].delta
        if delta and delta.content:
            yield delta.content


IMAGE_PROMPT = (
    "You are indexing an image so it can be found by search and used to answer questions. "
    "1) Transcribe ALL legible text exactly (OCR), preserving structure such as tables or lists. "
    "2) Then describe the image in detail: what it shows, charts/diagram contents and values, "
    "people/objects, and any key facts. Respond in plain text."
)


async def describe_image(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    data = base64.b64encode(path.read_bytes()).decode()
    return await complete(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": IMAGE_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}},
                ],
            }
        ],
        max_tokens=1500,
    )
