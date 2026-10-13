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
| support | Help page, Settings | README, docs and the connector status (never keys) |

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
