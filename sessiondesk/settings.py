"""Local settings and secrets.

Everything lives in one data directory (default ~/.sessiondesk, override with SESSIONDESK_HOME):

  settings.json   preferences: watchlist, alert thresholds, enabled connectors, AI provider/model
  secrets.json    API keys entered in the UI. Never returned by the API, never logged.

Environment variables win over secrets.json, so keys can also come from the shell or a .env file.
The API only ever reports whether a secret is set, where it comes from and its last four characters.
"""
from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path

DEFAULTS: dict = {
    "language": "English",              # language of AI answers
    "watchlist": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "SAP.DE", "ASML", "SIE.DE"],
    "universes": ["sp500", "nasdaq100", "dax40"],   # scanned for unusual moves
    "alerts": {
        "min_abs_pct": 3.0,             # universe: a move must exceed this ...
        "min_abs_z": 2.5,               # ... AND this many daily standard deviations
        "always_abs_pct": 8.0,          # ... or simply be this large
        "watchlist_abs_pct": 2.0,       # watchlist names alert earlier
        "watchlist_abs_z": 2.0,
        "scan_minutes": 5,
        "ai_explain": False,            # auto-explain alerts with the AI (costs tokens)
    },
    "events": {
        "warn_minutes": [30, 5, 1],     # warnings before high-impact releases
        "impact": ["high"],             # which impact levels warn
        "currencies": ["USD", "EUR", "GBP", "JPY", "CNY", "CHF", "CAD", "AUD"],
        "burst_seconds": 3,             # poll interval for release sources around an event
        "burst_before": 60,
        "burst_after": 240,
    },
    "news": {
        "squawk_seconds": 30,           # feeds that rate-limit are backed off automatically
        "markets_seconds": 120,
        "research_minutes": 60,
    },
    "ai": {
        "provider": "anthropic",
        "models": {
            "anthropic": "claude-opus-5-5",
            "openai": "gpt-5",
            "gemini": "gemini-2.5-flash",
            "openrouter": "openrouter/auto",
            "ollama": "llama3.1",
            "custom": "",
        },
        "custom_base_url": "",
        "ollama_url": "http://127.0.0.1:11434",
        "effort": "medium",             # Anthropic effort: low | medium | high
        "max_calls_per_day": 100,
    },
    "connectors": {},                   # {connector_id: {"enabled": bool, <non-secret fields>}}
    "preferences": {},                  # {capability: [connector ids in preferred order]}
    "feeds": {},                        # user overrides of the RSS feed lists, see features/news.py
    "privacy": {"mask_accounts": True},
}

ENV_ALIASES = {
    "anthropic.api_key": ["ANTHROPIC_API_KEY"],
    "openai.api_key": ["OPENAI_API_KEY"],
    "gemini.api_key": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
    "openrouter.api_key": ["OPENROUTER_API_KEY"],
}


def data_dir() -> Path:
    base = os.environ.get("SESSIONDESK_HOME") or str(Path.home() / ".sessiondesk")
    path = Path(base).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_dotenv(*paths: Path) -> None:
    """Minimal .env reader: KEY=VALUE lines, existing environment values are never overwritten."""
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and value and key not in os.environ:
                os.environ[key] = value


def deep_merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _write_private(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(path)


class Settings:
    def __init__(self, directory: Path):
        self.path = directory / "settings.json"
        self._lock = threading.Lock()
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = {}
        self._data = deep_merge(DEFAULTS, stored if isinstance(stored, dict) else {})

    @property
    def data(self) -> dict:
        return self._data

    def get(self, dotted: str, default=None):
        node = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def update(self, patch: dict) -> dict:
        with self._lock:
            self._data = deep_merge(self._data, patch)
            _write_private(self.path, self._data)
            return self._data

    def replace(self, key: str, value) -> dict:
        """Set a top-level key without merging (lists, or removing nested entries)."""
        with self._lock:
            self._data[key] = copy.deepcopy(value)
            _write_private(self.path, self._data)
            return self._data


class Secrets:
    """Key store. get() resolves env first, then the file. describe() is the only view the UI gets."""

    def __init__(self, directory: Path):
        self.path = directory / "secrets.json"
        self._lock = threading.Lock()
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = {}
        self._data: dict[str, str] = stored if isinstance(stored, dict) else {}

    @staticmethod
    def env_names(name: str) -> list[str]:
        generic = "SESSIONDESK_" + name.upper().replace(".", "_").replace("-", "_")
        return ENV_ALIASES.get(name, []) + [generic]

    def get(self, name: str) -> str | None:
        for env in self.env_names(name):
            if os.environ.get(env):
                return os.environ[env]
        value = self._data.get(name)
        return value or None

    def set(self, name: str, value: str) -> None:
        value = (value or "").strip()
        with self._lock:
            if value:
                self._data[name] = value
            else:
                self._data.pop(name, None)
            _write_private(self.path, self._data)

    def describe(self, name: str) -> dict:
        for env in self.env_names(name):
            if os.environ.get(env):
                return {"set": True, "source": f"env {env}", "hint": "…" + os.environ[env][-4:]}
        if self._data.get(name):
            return {"set": True, "source": "app", "hint": "…" + self._data[name][-4:]}
        return {"set": False, "source": None, "hint": None}
