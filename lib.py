"""Shared configuration, client instances, and utility functions."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from string import Template
from typing import Any, Callable

from dotenv import load_dotenv
from openai import APIError, OpenAI
from rich.console import Console

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
MAX_AGENT_STEPS = int(os.environ.get("MAX_AGENT_STEPS", "25"))
CRAWL4AI_BROWSER_MODE = os.environ.get("CRAWL4AI_BROWSER_MODE", "regular").lower()
CRAWL4AI_PAGE_TIMEOUT = int(os.environ.get("CRAWL4AI_PAGE_TIMEOUT", "15000"))  # ms
MAX_CONTENT_CHARS = 3000  # per fetched page before adding to agent context
NEWS_WINDOW_DAYS = 90

# ── Shared instances ──────────────────────────────────────────────────────────

console = Console()
ai = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
PROMPTS_DIR = Path(__file__).parent / "prompts"


# ── Prompt loading ────────────────────────────────────────────────────────────

def prompt(name: str, role: str, **kwargs) -> str:
    """Load a prompt template from prompts/ and substitute $variables."""
    template = (PROMPTS_DIR / f"{name}.{role}.txt").read_text(encoding="utf-8")
    return Template(template).substitute(kwargs)


# ── Utilities ─────────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text[:64]


def output_dir(name: str) -> Path:
    path = Path("output") / slugify(name)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_json(path: Path, data) -> None:
    if hasattr(data, "model_dump"):
        content = data.model_dump()
    elif isinstance(data, list):
        content = [d.model_dump() if hasattr(d, "model_dump") else d for d in data]
    else:
        content = data
    path.write_text(json.dumps(content, indent=2, default=str))


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def api_call_with_retry(fn: Callable[[], Any], retries: int = 3, delay: float = 3.0) -> Any:
    """Call fn(), retrying on transient API errors up to `retries` times."""
    for attempt in range(retries + 1):
        try:
            return fn()
        except APIError as e:
            if attempt == retries:
                raise
            console.print(f"  [yellow]API error (attempt {attempt + 1}/{retries + 1}): {e} — retrying in {delay:.0f}s[/yellow]")
            time.sleep(delay)
            delay *= 2  # exponential backoff


def ai_call(system: str, user: str) -> dict:
    """Call the AI with a single system+user exchange and return the parsed response."""
    return ai_call_messages([
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ])


def ai_call_messages(messages: list[dict]) -> dict:
    """Call the AI with a full message history and return the parsed response."""
    response = api_call_with_retry(lambda: ai.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.1,
    ))
    return json.loads(response.choices[0].message.content)
