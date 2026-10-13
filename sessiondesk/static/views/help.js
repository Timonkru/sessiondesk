// Help: quick start, shortcuts, and the AI support chat that answers from the bundled documentation.
import { api } from "../lib/api.js";
import { h, section, note, ext } from "../lib/ui.js";

export async function render(root, _params, ctx) {
  ctx.setContext({ page: "Help & support" });
  const health = await api("/api/health", { fresh: true });
  const q = h("input", { type: "text", placeholder: "e.g. How do I connect MetaTrader 5?  /  Where do I put my OpenAI key?", style: { width: "min(560px, 100%)" } });
  const ask = () => { if (q.value.trim()) { ctx.ask(q.value.trim(), { page: "Help & support" }); q.value = ""; } };
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") ask(); });
  root.append(
    h("div", { class: "pagehead" }, h("h1", null, "Help"), h("span", { class: "meta" }, `version ${health.version} · data folder ${health.data_dir}`)),
    section("Ask the built-in support", h("div", { class: "toolbar" }, q, h("button", { onclick: ask }, "Ask")),
      note(health.ai_ready ? "Answers come from the README and docs/ shipped with SessionDesk, plus the current connector status (never your keys)."
                           : "Support answers need an AI provider: Settings → AI (your own key, or a local Ollama model).")),
    section("Quick start", h("ol", null,
      h("li", null, "Markets, stocks, news, calendar, forced flows, research and macro work immediately - no account needed."),
      h("li", null, "Type a ticker or company in the search bar (press / to jump there). Type a question instead and the AI answers about the page you are on."),
      h("li", null, "Settings → Connectors: add your own keys for paid/keyed feeds (news, calendars with actual values, fundamentals) and for the AI."),
      h("li", null, "Accounts & EAs: attach bridge/SessionDeskBridge.mq5 to one MetaTrader 5 chart for a read-only view of accounts, positions, running EAs - and actual values of economic releases within seconds."),
      h("li", null, "Jobs: register your own scripts (.bat, .py, .ps1 …) and run them by click, on a schedule or as a service."),
      h("li", null, "Settings → Alerts: allow desktop notifications and keep the tab open to get release warnings and unusual-move alerts."))),
    section("Keyboard", h("dl", { class: "kv" },
      h("dt", null, "/"), h("dd", null, "search / ask"), h("dt", null, "Enter in search"), h("dd", null, "open the stock, or ask the AI"),
      h("dt", null, "? question"), h("dd", null, "force an AI question"), h("dt", null, "Esc"), h("dd", null, "close the search list"))),
    section("What SessionDesk will not do", note("It never places, modifies or closes orders - broker and EA connections are read-only. The AI explains and summarizes data the app computed; " +
      "it is instructed not to give buy/sell instructions, price targets or forecasts. Market data from free sources can be delayed or wrong; every panel names its source.")),
    section("Project", h("p", null, ext("https://github.com/Timonkru/sessiondesk", "github.com/Timonkru/sessiondesk"), " · MIT license · issues and contributions welcome")));
}
