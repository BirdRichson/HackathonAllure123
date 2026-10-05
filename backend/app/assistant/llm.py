"""Языковая модель через бесплатные API: Groq и Google Gemini.

Ключи берутся из переменных окружения или из файла `.env` в корне проекта:
    GROQ_API_KEY    — https://console.groq.com/keys
    GEMINI_API_KEY  — https://aistudio.google.com/apikey

Настройки (необязательно):
    ALLUR_LLM_PROVIDER  auto | groq | gemini | off   (auto — по очереди все, у которых есть ключ)
    ALLUR_LLM_ORDER     порядок для auto, по умолчанию «groq,gemini»
    GROQ_MODEL          модель Groq; можно несколько через запятую — при лимите берётся следующая
    GEMINI_MODEL        модель Gemini; так же
    ALLUR_LLM_TIMEOUT   таймаут запроса, секунды (по умолчанию 25)

Ответ всегда JSON (режим структурированного ответа у обоих провайдеров).
Ответы кэшируются в `data/ai_cache/`: тот же запрос без интернета берётся из кэша — показ не зависит от сети.
Если ключей нет или сеть недоступна, вызывающий код переходит на офлайн-логику (правила и локальные модели).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.config import AI_CACHE_DIR

DEFAULT_MODELS = {
    "groq": "openai/gpt-oss-120b,llama-3.3-70b-versatile",
    "gemini": "gemini-3.5-flash,gemini-3.1-flash-lite",
}
KEY_ENV = {"groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY"}
LABELS = {"groq": "Groq", "gemini": "Google Gemini"}


class LLMError(Exception):
    """Ни один провайдер не ответил. В тексте — причины по каждому."""


@dataclass
class LLMResult:
    data: dict[str, Any]
    provider: str
    model: str
    cached: bool = False
    latency_ms: int = 0

    @property
    def label(self) -> str:
        return f"{LABELS.get(self.provider, self.provider)} · {self.model}"


class ProviderError(Exception):
    def __init__(self, message: str, status: int | None = None, fatal: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.fatal = fatal          # ключ неверный — этот провайдер больше не пробуем


def _models(name: str) -> list[str]:
    raw = os.environ.get(f"{name.upper()}_MODEL") or DEFAULT_MODELS[name]
    return [m.strip() for m in raw.split(",") if m.strip()]


def _check(r: httpx.Response) -> None:
    if r.status_code < 400:
        return
    try:
        detail = r.json().get("error", {})
        msg = detail.get("message") if isinstance(detail, dict) else str(detail)
    except Exception:
        msg = r.text[:200]
    raise ProviderError(f"HTTP {r.status_code}: {msg}", status=r.status_code, fatal=r.status_code in (401, 403))


class Groq:
    """Groq: OpenAI-совместимый Chat Completions, режим JSON."""

    name = "groq"
    URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, key: str) -> None:
        self.key = key
        self.models = _models(self.name)

    def call(self, http: httpx.Client, model: str, system: str, user: str, max_tokens: int) -> str:
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2,
            "max_completion_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        if "gpt-oss" in model:          # модели с рассуждением: короткое рассуждение — быстрее и меньше токенов
            body["reasoning_effort"] = os.environ.get("GROQ_REASONING_EFFORT", "low")
        r = http.post(self.URL, headers={"Authorization": f"Bearer {self.key}"}, json=body)
        _check(r)
        return r.json()["choices"][0]["message"]["content"] or ""


class Gemini:
    """Google Gemini: generateContent с ответом application/json."""

    name = "gemini"
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, key: str) -> None:
        self.key = key
        self.models = _models(self.name)

    def call(self, http: httpx.Client, model: str, system: str, user: str, max_tokens: int) -> str:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.2,
                # у моделей с «размышлением» оно тоже расходует лимит ответа — даём запас
                "maxOutputTokens": max(max_tokens * 2, 8192),
            },
        }
        r = http.post(self.URL.format(model=model), headers={"x-goog-api-key": self.key}, json=body)
        _check(r)
        cands = r.json().get("candidates") or []
        if not cands:
            raise ProviderError("пустой ответ (возможно, сработал фильтр безопасности)")
        parts = cands[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts if not p.get("thought"))


PROVIDERS = {"groq": Groq, "gemini": Gemini}


def parse_json(text: str) -> dict[str, Any]:
    """JSON из ответа модели: снимает ```-обёртку и лишний текст вокруг объекта."""
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        a, b = s.find("{"), s.rfind("}")
        if a < 0 or b <= a:
            raise ProviderError("ответ не JSON") from None
        try:
            data = json.loads(s[a : b + 1])
        except json.JSONDecodeError as e:
            raise ProviderError(f"ответ не JSON: {e}") from None
    if not isinstance(data, dict):
        raise ProviderError("ожидался JSON-объект")
    return data


@dataclass
class CallInfo:
    at: str
    task: str
    ok: bool
    provider: str | None = None
    model: str | None = None
    cached: bool = False
    latency_ms: int = 0
    error: str | None = None


@dataclass
class LLMClient:
    cache_dir: Path = field(default_factory=lambda: Path(os.environ.get("ALLUR_AI_CACHE_DIR") or AI_CACHE_DIR))
    transport: httpx.BaseTransport | None = None      # для тестов — подмена сети
    last: CallInfo | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _disabled: dict[str, str] = field(default_factory=dict)   # провайдеры с неверным ключом

    # ── настройки ──

    @property
    def mode(self) -> str:
        return os.environ.get("ALLUR_LLM_PROVIDER", "auto").strip().lower() or "auto"

    def providers(self) -> list[Groq | Gemini]:
        mode = self.mode
        if mode == "off":
            return []
        order = [mode] if mode in PROVIDERS else [
            p.strip() for p in os.environ.get("ALLUR_LLM_ORDER", "groq,gemini").split(",") if p.strip() in PROVIDERS
        ]
        out = []
        for name in order:
            key = os.environ.get(KEY_ENV[name], "").strip()
            if key and name not in self._disabled:
                out.append(PROVIDERS[name](key))
        return out

    @property
    def available(self) -> bool:
        return bool(self.providers())

    def status(self) -> dict[str, Any]:
        mode = self.mode
        items = []
        for name in PROVIDERS:
            items.append({
                "name": name, "label": LABELS[name],
                "configured": bool(os.environ.get(KEY_ENV[name], "").strip()),
                "models": _models(name),
                "disabled_reason": self._disabled.get(name),
            })
        n_cache = len(list(self.cache_dir.glob("*.json"))) if self.cache_dir.is_dir() else 0
        return {
            "mode": mode,
            "online": mode != "off" and self.available,
            "providers": items,
            "cache_entries": n_cache,
            "last_call": None if self.last is None else self.last.__dict__,
        }

    # ── кэш ──

    def _cache_key(self, task: str, system: str, user: str) -> str:
        raw = json.dumps({"task": task, "system": system, "user": user}, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def _cache_get(self, key: str) -> dict | None:
        p = self.cache_dir / f"{key}.json"
        if not p.is_file():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _cache_put(self, key: str, task: str, res: LLMResult) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            payload = {"task": task, "provider": res.provider, "model": res.model, "data": res.data,
                       "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            (self.cache_dir / f"{key}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                                        encoding="utf-8")
        except OSError:
            pass

    # ── вызов ──

    def complete_json(self, task: str, system: str, user: str, *, max_tokens: int = 2048,
                      use_cache: bool = True) -> LLMResult:
        """Ответ модели в виде JSON-объекта. Сначала кэш, затем провайдеры по очереди.

        Бросает LLMError, если ответа нет ни в кэше, ни у провайдеров (нет ключей, нет сети, лимиты).
        """
        key = self._cache_key(task, system, user)
        if use_cache:
            hit = self._cache_get(key)
            if hit is not None:
                res = LLMResult(hit["data"], hit["provider"], hit["model"], cached=True)
                self._remember(CallInfo(_now(), task, True, res.provider, res.model, cached=True))
                return res

        providers = self.providers()
        if not providers:
            msg = "LLM выключен (ALLUR_LLM_PROVIDER=off)" if self.mode == "off" else \
                "нет ключа API: задайте GROQ_API_KEY или GEMINI_API_KEY в .env"
            self._remember(CallInfo(_now(), task, False, error=msg))
            raise LLMError(msg)

        errors = []
        timeout = float(os.environ.get("ALLUR_LLM_TIMEOUT", "25"))
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=6.0), transport=self.transport) as http:
            for prov in providers:
                for model in prov.models:
                    t0 = time.monotonic()
                    try:
                        text = prov.call(http, model, system, user, max_tokens)
                        data = parse_json(text)
                    except ProviderError as e:
                        errors.append(f"{prov.name}/{model}: {e}")
                        if e.fatal:
                            self._disabled[prov.name] = str(e)
                            break
                        continue
                    except (httpx.HTTPError, KeyError, ValueError) as e:
                        errors.append(f"{prov.name}/{model}: {type(e).__name__}: {e}")
                        if isinstance(e, httpx.ConnectError):
                            break       # нет сети до провайдера — остальные модели того же провайдера не помогут
                        continue
                    res = LLMResult(data, prov.name, model, latency_ms=int((time.monotonic() - t0) * 1000))
                    self._cache_put(key, task, res)
                    self._remember(CallInfo(_now(), task, True, prov.name, model, latency_ms=res.latency_ms))
                    return res
        msg = "; ".join(errors) or "нет ответа"
        self._remember(CallInfo(_now(), task, False, error=msg[:500]))
        raise LLMError(msg)

    def _remember(self, info: CallInfo) -> None:
        with self._lock:
            self.last = info


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_client: LLMClient | None = None


def get_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
