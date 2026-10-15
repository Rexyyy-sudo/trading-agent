import { tool } from "@opencode-ai/plugin"
import { failureMessage, runCli } from "../lib/cli"

export const news = tool({
  description: [
    "Macro/news risk report for a symbol from the trading-agent framework.",
    "Risk level may be UNKNOWN when no live news provider is configured - report that honestly, never guess events.",
    "EXTREME risk makes the framework output NO TRADE; HIGH adds a caution and can reduce size.",
  ].join(" "),
  args: {
    symbol: tool.schema.string().describe("Symbol, e.g. XAUUSD, BTCUSDT, EURUSD"),
    hours: tool.schema.number().optional().describe("Lookahead window in hours (optional override)"),
  },
  async execute(args) {
    const cliArgs = ["news", args.symbol]
    if (args.hours !== undefined) cliArgs.push("--hours", String(args.hours))
    const result = runCli(cliArgs, 120_000)
    return {
      title: `news risk ${args.symbol}`,
      output: result.ok ? result.stdout : failureMessage(result),
    }
  },
})
