"""Connector contract and the hub that routes requests to them.

A connector wraps one outside system (a data vendor, a feed, a broker, MetaTrader). It declares:

  tier          "free"      works out of the box, no account
                "free-key"  free account/key required (user brings it)
                "paid"      paid subscription required (user brings the key)
  capabilities  which normalized calls it answers (quotes, history, news, calendar, ...)
  fields        what the user must enter (secret fields go to the key store, never back to the UI)
  verified      False = written against the vendor's public docs but never run with a live key.
                The UI shows this. Flip it to True only after a real call succeeded.

Normalized shapes (every connector returns these, so the features never care about the vendor):

  Quote    {symbol, price, prev_close, change, change_pct, time, currency?, name?, spark?}
  Bar      {t, o, h, l, c, v}
  News     {id, title, url, source, published, summary?, symbols?, provider}
  Event    {id, ts, currency, country?, title, impact: high|medium|low|holiday,
            actual?, forecast?, previous?, unit?, source}

Trading connectors are READ-ONLY by design: account, positions, running EAs. SessionDesk never
sends, modifies or cancels an order.
"""
from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from typing import Any

CAPABILITIES = ("quotes", "history", "search", "profile", "news", "symbol_news", "calendar",
                "earnings", "filings", "series", "account", "positions", "eas")


@dataclass
class Field:
    key: str
    label: str
    secret: bool = True
    required: bool = True
    help: str = ""
    placeholder: str = ""


@dataclass
class Ctx:
    """Everything a connector or feature may touch."""
    settings: Any
    secrets: Any
    cache: Any
    http: Any                  # httpx.AsyncClient
    broker: Any
    db: Any = None
    data_dir: Any = None
    hub: Any = None
    extras: dict = field(default_factory=dict)


class ConnectorError(RuntimeError):
    pass


class Connector:
    id = ""
    name = ""
    tier = "free"
    kind = "data"              # data | broker | ai | news | calendar
    capabilities: tuple[str, ...] = ()
    fields: tuple[Field, ...] = ()
    homepage = ""
    description = ""
    verified = True
    default_enabled = True

    def __init__(self, ctx: Ctx):
        self.ctx = ctx

    # ------------------------------------------------------------ config
    def secret(self, key: str) -> str | None:
        return self.ctx.secrets.get(f"{self.id}.{key}")

    def option(self, key: str, default=None):
        value = self.ctx.settings.get(f"connectors.{self.id}.{key}")
        return default if value in (None, "") else value

    def value(self, f: Field):
        return self.secret(f.key) if f.secret else self.option(f.key)

    def configured(self) -> bool:
        return all(self.value(f) for f in self.fields if f.required)

    def enabled(self) -> bool:
        flag = self.ctx.settings.get(f"connectors.{self.id}.enabled")
        if flag is None:
            return self.default_enabled
        return bool(flag)

    def active(self) -> bool:
        return self.enabled() and self.configured()

    def describe(self) -> dict:
        return {
            "id": self.id, "name": self.name, "tier": self.tier, "kind": self.kind,
            "capabilities": list(self.capabilities), "homepage": self.homepage,
            "description": self.description, "verified": self.verified,
            "enabled": self.enabled(), "configured": self.configured(), "active": self.active(),
            "fields": [{"key": f.key, "label": f.label, "secret": f.secret, "required": f.required,
                        "help": f.help, "placeholder": f.placeholder,
                        **({"state": self.ctx.secrets.describe(f"{self.id}.{f.key}")} if f.secret
                           else {"value": self.option(f.key, "")})}
                       for f in self.fields],
        }

    async def test(self) -> dict:
        """Cheapest real call that proves the connector works. Override per connector."""
        return {"ok": self.configured(), "detail": "configured" if self.configured() else "missing fields"}

    # ------------------------------------------------------------ helpers
    async def get_json(self, url: str, *, params: dict | None = None, headers: dict | None = None,
                       timeout: float = 12.0):
        resp = await self.ctx.http.get(url, params=params, headers=headers, timeout=timeout)
        if resp.status_code == 401 or resp.status_code == 403:
            raise ConnectorError(f"{self.name}: access denied (HTTP {resp.status_code}) - check the key / plan")
        if resp.status_code == 429:
            raise ConnectorError(f"{self.name}: rate limit reached (HTTP 429)")
        if resp.status_code >= 400:
            raise ConnectorError(f"{self.name}: HTTP {resp.status_code}")
        return resp.json()


class PlannedConnector:
    """Catalog entry for a connector that is not implemented yet (shown greyed out in the UI)."""

    def __init__(self, id: str, name: str, tier: str, kind: str, capabilities: tuple, homepage: str, description: str):
        self.id, self.name, self.tier, self.kind = id, name, tier, kind
        self.capabilities, self.homepage, self.description = capabilities, homepage, description

    def describe(self) -> dict:
        return {"id": self.id, "name": self.name, "tier": self.tier, "kind": self.kind,
                "capabilities": list(self.capabilities), "homepage": self.homepage,
                "description": self.description, "planned": True, "verified": False,
                "enabled": False, "configured": False, "active": False, "fields": []}


class Hub:
    """Owns all connectors; picks the right one(s) for a capability."""

    def __init__(self, ctx: Ctx, connectors: list[Connector], planned: list[PlannedConnector] | None = None):
        self.ctx = ctx
        self.connectors = {c.id: c for c in connectors}
        self.planned = planned or []

    def get(self, cid: str) -> Connector | None:
        return self.connectors.get(cid)

    def candidates(self, capability: str) -> list[Connector]:
        able = [c for c in self.connectors.values() if capability in c.capabilities and c.active()]
        preferred = self.ctx.settings.get(f"preferences.{capability}") or []
        # User order first. Otherwise paid sources lead. For prices, the free Yahoo feed (one call per
        # 20 symbols, global coverage) beats free-key APIs that cost one rate-limited call per symbol;
        # for news and calendars, any keyed source adds something the free feeds lack.
        if capability in ("quotes", "history"):
            rank = {"paid": 0, "free": 1, "free-key": 2}
        else:
            rank = {"paid": 0, "free-key": 1, "free": 2}
        able.sort(key=lambda c: (preferred.index(c.id) if c.id in preferred else len(preferred),
                                 rank.get(c.tier, 3)))
        return able

    async def first(self, capability: str, method: str, *args, **kwargs) -> dict:
        """Ask candidates in order; return the first success as {"data": ..., "source": id}."""
        errors = []
        for conn in self.candidates(capability):
            try:
                data = await getattr(conn, method)(*args, **kwargs)
            except Exception as exc:
                errors.append(f"{conn.id}: {exc}")
                continue
            if data:
                return {"data": data, "source": conn.id}
            errors.append(f"{conn.id}: empty")
        return {"error": "; ".join(errors) or f"no active connector for '{capability}'"}

    async def gather(self, capability: str, method: str, *args, **kwargs) -> dict:
        """Ask all candidates in parallel and return {source: result_or_error}. For news/calendar merges."""
        conns = self.candidates(capability)

        async def one(conn):
            try:
                return conn.id, await getattr(conn, method)(*args, **kwargs)
            except Exception as exc:
                return conn.id, {"error": f"{type(exc).__name__}: {exc}"}
        pairs = await asyncio.gather(*(one(c) for c in conns))
        return dict(pairs)

    def catalog(self) -> list[dict]:
        return [c.describe() for c in self.connectors.values()] + [p.describe() for p in self.planned]


def stable_id(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8", "ignore")).hexdigest()[:16]
