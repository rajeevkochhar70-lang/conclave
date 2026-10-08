"""Optional LLM layer with a fallback chain. Returns None when no key/model answers.

Agents never compute with the LLM; they hand it facts and get prose back.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request

from .config import Config

log = logging.getLogger(__name__)
NUM_RE = re.compile(r"(?<![\w.])[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?%?|(?<![\w.])[-+]?\d+(?:\.\d+)?%?")


def _post(url: str, headers: dict, body: dict, timeout: int = 60) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _call_anthropic(key: str, model: str, system: str, prompt: str) -> str:
    out = _post("https://api.anthropic.com/v1/messages",
                {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                {"model": model, "max_tokens": 600, "system": system,
                 "messages": [{"role": "user", "content": prompt}]})
    return "".join(b.get("text", "") for b in out.get("content", []))


def _call_openrouter(key: str, model: str, system: str, prompt: str) -> str:
    out = _post("https://openrouter.ai/api/v1/chat/completions",
                {"Authorization": f"Bearer {key}", "content-type": "application/json"},
                {"model": model, "max_tokens": 600,
                 "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]})
    return out["choices"][0]["message"]["content"]


class LLM:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.last_model: str | None = None

    def available(self) -> bool:
        return self.cfg.llm_enabled and bool(self.cfg.anthropic_key or self.cfg.openrouter_key)

    def complete(self, system: str, prompt: str) -> str | None:
        if not self.available():
            return None
        for spec in self.cfg.llm_models:
            provider, _, model = spec.partition(":")
            try:
                if provider == "anthropic" and self.cfg.anthropic_key:
                    text = _call_anthropic(self.cfg.anthropic_key, model, system, prompt)
                elif provider == "openrouter" and self.cfg.openrouter_key:
                    text = _call_openrouter(self.cfg.openrouter_key, model, system, prompt)
                else:
                    continue
                if text and text.strip():
                    self.last_model = spec
                    return text.strip()
            except urllib.error.HTTPError as e:
                log.warning("%s: HTTP %s, trying next model", spec, e.code)
            except Exception as e:  # noqa: BLE001
                log.warning("%s: %s, trying next model", spec, e)
        return None


def numbers_in(text: str) -> list[float]:
    vals = []
    for m in NUM_RE.findall(text):
        try:
            vals.append(float(m.replace(",", "").rstrip("%")))
        except ValueError:
            pass
    return vals


def check_numbers(text: str, facts: dict, tol: float = 0.011) -> list[float]:
    """Numbers in `text` that do not appear in `facts` (within tolerance, incl. rounding). Golden rule."""
    allowed: set[float] = set()

    def walk(v):
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)) and v == v:
            allowed.update({float(v), round(float(v), 0), round(float(v), 1), round(float(v), 2)})
            allowed.update({round(float(v) * 100, 0), round(float(v) * 100, 1)})  # pct forms
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
        elif isinstance(v, str):
            allowed.update(numbers_in(v))

    walk(facts)
    allowed.update({7.0, 10.0, 14.0, 20.0, 21.0, 22.0, 30.0, 34.0, 50.0, 52.0, 60.0, 89.0, 100.0, 120.0,
                    150.0, 200.0, 252.0})  # indicator periods / "52-week" / percent base
    bad = []
    for n in numbers_in(text):
        if abs(n) <= 5 and float(n).is_integer():
            continue  # "3 of 5 desks", "2 backups" — counts, not data
        if not any(abs(n - a) <= tol * max(1.0, abs(a)) for a in allowed):
            bad.append(n)
    return bad
