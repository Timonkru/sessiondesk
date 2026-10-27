# AI assistant

## One rule: the code computes, the model words

The assistant receives the data of the page you are on as JSON, built by SessionDesk. Its system
prompt requires it to

1. use only facts and numbers present in that JSON (or in your message) and say when something is missing,
2. give no buy/sell/hold instructions, no position sizing, no price targets and no direction forecasts,
3. separate what the data shows from interpretation and name the weak spots (small samples, stale or vendor data),
4. answer compactly in the language set in **Settings → AI**.

## Modes

| Mode | Where | What it gets |
|---|---|---|
| ask | search bar on any page, "Ask AI" | the current page's data |
| explain | "explain with AI" on an alert, optional auto-explain | the computed move facts (beta split, earnings, headlines) |
| summarize | research reader | the article text |
| briefing | Today, "Pre-session briefing" | markets with observation times; local schedule and event proximity; account freshness and held markets; volatility, risk ratios, rates, credit and implied Fed path; earnings, computed levels, flow mechanisms, scanner anomalies, data-hub warnings and selected archived news |
| review | Today, "Weekly review" | computed account/setup/market statistics for rolling 7 days, the preceding nonoverlapping 23 days and their 30-day total; risk coverage, selected examples/notes and a separate current risk snapshot |
| support | Help page, Settings | README, docs and the connector status (never keys) |

## Pre-session briefing

The briefing leads with the session's main tension, then develops two or three themes using evidence,
counterevidence and the implications for the markets on your desk. It closes with a selective session
roadmap, relevant desk risks/reference levels and observations that would change the assessment.
Economic mechanisms are interpretation; a headline alone does not establish the cause of a price move.
It gives no trade instructions or directional forecasts.

Times use the EU session timezone (Europe/Berlin by default), with explicit dates and offsets so the
different US and European clock-change weeks remain clear. Calendar proximity is computed within
15 minutes of an explicit schedule entry; it does not infer a strategy window from entry labels.
News covers at least 18 hours and goes back to the previous US cash close, including weekends.
The archive is selected by impact, relevance and recency, with duplicate titles removed; it is not a
complete news wire. Quote timestamps, slower macro dates, stale accounts and unavailable sources
remain visible to the model. Optional sources have separate timeouts so one failure does not discard
the other evidence. File paths, API keys and position tickets are excluded from briefing context.

The target is 650-950 words. The briefing has a larger output allowance than a short alert explanation
so reasoning and the final sections have room to finish; actual token use remains visible in Settings.
The richer context can increase API cost. Click **write now** again after a server restart to replace
an older saved briefing.

## Weekly review

The review explains result drivers, payoff asymmetry, concentration and process weaknesses rather
than listing every setup. All figures are computed in Python. The review uses every eligible closed
position in the available deal exports, not just the newest 200 journal entries. Duplicate tickets,
partial position exits, missing entries and reversal positions are handled explicitly. Export history
may be incomplete; exclusions and annotation/sample limits are reported in context. If deal exports
are unavailable, the journal is used as a labelled fallback with weaker closure verification.

Per-account statistics include net per trade, average gain/loss, profit factor, closed-P/L drawdown,
losing streaks where ordering is known, active days, holding time and the result without the largest
winning trade. Itemized profit, commission, swap and fee are preserved where exported. Net already
includes exported costs; spread and slippage attribution is not available. These position-lifecycle
results are assigned to the final close, so they can differ from cash movements booked in that week.
They are not a reconciled account-equity return. Accounts/currencies remain separate.

Configured copy magics (or explicitly named copier groups when none are configured) are marked as
copies, never independent strategy samples. No source/copy matching or execution-quality attribution
is inferred. Trade count alone does not establish statistical reliability. Confirmed initial-risk R
and first-observed risk proxy R have separate coverage. A first-seen "stop none" entry is historical;
current missing stops come only from fresh broker positions. Notes and activity are labelled samples.

The review targets 650-950 words and has the same larger output allowance as the briefing. The richer
context can increase API cost. Existing saved reviews are not rewritten automatically by a code update;
restart SessionDesk, then click **write now** for a new review.

## Providers

| Provider | Key | Notes |
|---|---|---|
| Anthropic | `ANTHROPIC_API_KEY` | official SDK; default model `claude-opus-5-5`, Sonnet 5.5 and Haiku 5.5 are cheaper. Server-side refusal fallback is enabled for models that support it; the system prompt is cached. |
| OpenAI | `OPENAI_API_KEY` | Chat Completions API, any model id your key can use |
| Google Gemini | `GEMINI_API_KEY` | Generative Language API |
| OpenRouter | `OPENROUTER_API_KEY` | many vendors behind one key |
| Ollama | none | local models, nothing leaves the machine |
| OpenAI-compatible server | optional | LM Studio, vLLM, Groq, Together and others; set the base URL in Settings → AI |

Costs stay visible: a daily call cap (default 100), token counts per answer, and a cost estimate
for Anthropic models. Answers stream, so the first words appear while the rest is still generated.
