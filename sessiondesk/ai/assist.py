"""AI assistance on every page. One rule: the code computes, the model words.

Every number the model may use arrives as JSON built by SessionDesk itself (the data the current
page shows). The system prompt forbids figures that are not in that JSON, trade instructions,
price targets and direction calls. The model explains, summarizes, connects - it does not decide.

Modes
  ask        a question about whatever page is open (context = that page's data)
  explain    turn a computed move/alert explanation into plain language
  summarize  summarize an article from the reader (claims vs evidence, what matters for markets)
  support    how-to questions about SessionDesk itself, answered from the bundled docs
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import AsyncIterator

from .providers import estimate_cost

ROOT = Path(__file__).resolve().parents[2]

GUARD = (
    "Rules you must follow:\n"
    "1. Use ONLY facts and numbers that appear in the CONTEXT JSON or in the user's message. Never invent, estimate or "
    "recompute a figure. If something is not in the context, say that it is missing.\n"
    "2. No personalised investment advice: no buy/sell/hold instructions, no position sizing, no price targets, "
    "no forecasts of direction.\n"
    "3. Separate what the data shows from possible interpretations, and name the weak spots (small samples, stale data, "
    "vendor data quality).\n"
    "4. Be compact and concrete. Use short paragraphs or a few bullets; no pep talk, no disclaimers beyond what matters.\n"
    "5. Answer in {language}.")

MODES = {
    "ask": "You are the analyst assistant inside SessionDesk, a market desk application. The user is looking at the page "
           "described in the CONTEXT and asks about it.",
    "explain": "You explain an unusual stock move to a trader. The CONTEXT holds the computed facts: move, volatility-adjusted "
               "size (sigma), benchmark and sector moves, beta, the stock-specific remainder, earnings timing and headlines. "
               "Write 2-4 sentences: what moved, how much of it the market/sector explains, and what the headlines say - "
               "attribute causes only to the given headlines and say so when no headline explains it.",
    "summarize": "You summarize a research article or news story for a trader. Structure: (1) the core claim in one sentence, "
                 "(2) the evidence offered and its quality (sample, period, method - only if stated), (3) what it could mean "
                 "for markets, labelled as interpretation, (4) open questions. Quote numbers only from the article text.",
    "briefing": "You write the pre-session briefing for a trader from the CONTEXT JSON (all times in it are UTC - say so). "
                "Structure with short headings: 1) Overnight - what moved and the headlines behind it; 2) Today - the scheduled "
                "releases with time, forecast and previous, and which of the trader's own schedule entries collide with them; "
                "3) Context - volatility state, forced flows in the next days, unusual single-stock moves; 4) Accounts - day P/L, "
                "room to the loss limits, rule flags; 5) Watch list - what the data says deserves attention. No trade instructions.",
    "review": "You review the trader's last week from the CONTEXT JSON: closed trades by setup (n, net, win rate), journal "
              "entries (R where an initial risk is confirmed), notes and logged activity. Structure: what worked and what did not "
              "per setup, EA vs manual trades, rule breaches, recurring patterns in the notes. Always state n and call results "
              "with small n anecdotal. No trade instructions, no predictions.",
    "support": "You are SessionDesk's built-in help. Answer how-to questions about installing, configuring and using the app "
               "from the DOCUMENTATION below. Give exact menu paths and file names. If the docs do not cover the question, "
               "say so and point to the project's GitHub issues.",
}


def _compact(obj, depth: int = 0):
    if isinstance(obj, float):
        return round(obj, 4)
    if isinstance(obj, dict):
        return {k: _compact(v, depth + 1) for k, v in obj.items()
                if v not in (None, "", [], {}) and k not in ("spark", "intraday", "bars", "buffer")}
    if isinstance(obj, (list, tuple)):
        limit = 60 if depth < 3 else 20
        return [_compact(v, depth + 1) for v in obj[:limit]]
    return obj


def context_json(context, max_chars: int = 60_000) -> str:
    text = json.dumps(_compact(context or {}), ensure_ascii=False, default=str)
    if len(text) > max_chars:
        text = text[:max_chars] + " …[truncated]"
    return text


def docs_text(max_chars: int = 120_000) -> str:
    parts = []
    for path in [ROOT / "README.md"] + sorted((ROOT / "docs").glob("*.md")):
        try:
            parts.append(f"=== {path.name} ===\n{path.read_text(encoding='utf-8')}")
        except OSError:
            continue
    text = "\n\n".join(parts) or "(documentation files not found next to the installation)"
    return text[:max_chars]


def system_prompt(mode: str, language: str, catalog: list[dict] | None = None) -> str:
    base = MODES.get(mode, MODES["ask"]) + "\n\n" + GUARD.format(language=language)
    if mode == "support":
        status = [{"id": c["id"], "name": c["name"], "tier": c["tier"], "active": c.get("active"), "planned": c.get("planned", False)}
                  for c in (catalog or [])]
        base += "\n\nCONNECTOR STATUS (no secrets):\n" + json.dumps(status) + "\n\nDOCUMENTATION:\n" + docs_text()
    return base


def pick_provider(ctx, wanted: str | None = None):
    pid = wanted or ctx.settings.get("ai.provider") or "anthropic"
    prov = ctx.hub.get(pid)
    if prov and prov.kind == "ai" and prov.active():
        return prov
    for p in ctx.hub.connectors.values():          # fall back to any configured AI provider
        if p.kind == "ai" and p.active() and p.id != "ollama":
            return p
    return prov if prov and prov.kind == "ai" else None


async def chat(ctx, mode: str, question: str, context=None, history: list[dict] | None = None,
               provider: str | None = None) -> AsyncIterator[dict]:
    """Yields {"type": "meta"|"text"|"done"|"error", ...} - the API turns these into an event stream."""
    prov = pick_provider(ctx, provider)
    if prov is None or not prov.active():
        yield {"type": "error", "error": "No AI provider configured. Settings -> AI: add your own key (Anthropic, OpenAI, Gemini, "
                                         "OpenRouter) or run a local model with Ollama."}
        return
    cap = int(ctx.settings.get("ai.max_calls_per_day") or 100)
    used = await ctx.db.run(ctx.db.usage_today)
    if used["calls"] >= cap:
        yield {"type": "error", "error": f"Daily AI call limit reached ({cap}). Change it in Settings -> AI."}
        return
    language = ctx.settings.get("language") or "English"
    system = system_prompt(mode, language, ctx.hub.catalog() if mode == "support" else None)
    msgs = [m for m in (history or [])[-8:] if m.get("role") in ("user", "assistant") and m.get("content")]
    content = question.strip()
    if mode != "support":
        content = f"CONTEXT JSON:\n{context_json(context)}\n\nQUESTION:\n{content or 'Explain this.'}"
    msgs.append({"role": "user", "content": content})
    effort = {"explain": "low", "summarize": "low", "support": "low"}.get(mode, ctx.settings.get("ai.effort") or "medium")
    max_tokens = {"explain": 800, "briefing": 3000, "review": 3000}.get(mode, 4000)
    yield {"type": "meta", "provider": prov.id, "model": prov.model()}
    started = time.time()
    try:
        async for chunk in prov.stream(system, msgs, max_tokens=max_tokens, effort=effort):
            yield {"type": "text", "text": chunk}
    except Exception as exc:
        yield {"type": "error", "error": str(exc)}
        return
    usage = prov.last_usage or {}
    cost = estimate_cost(usage)
    await ctx.db.run(ctx.db.log_usage, mode, prov.id, usage, cost)
    yield {"type": "done", "usage": usage, "cost": cost, "seconds": round(time.time() - started, 1)}


async def complete(ctx, mode: str, question: str, context=None) -> dict:
    text, meta = "", {}
    async for ev in chat(ctx, mode, question, context):
        if ev["type"] == "text":
            text += ev["text"]
        elif ev["type"] == "error":
            return {"error": ev["error"]}
        else:
            meta.update(ev)
    return {"text": text.strip(), **{k: v for k, v in meta.items() if k != "type"}}
