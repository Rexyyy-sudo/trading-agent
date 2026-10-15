import { tool } from "@opencode-ai/plugin"
import { failureMessage, runCli } from "../lib/cli"

export const market_data = tool({
  description: [
    "Market data utilities for the local trading-agent framework.",
    "action=price: latest price and its provenance (real data or explicit failure).",
    "action=providers: which data providers are available (binance/yahoo public, twelvedata/alphavantage need API keys, csv = local files).",
    "action=fetch: download candles to data/raw as CSV for offline use.",
    "Never fabricate prices - this tool only returns real provider output or an explicit error.",
  ].join(" "),
  args: {
    action: tool.schema.enum(["price", "providers", "fetch"]).describe("What to do"),
    symbol: tool.schema.string().optional().describe("Symbol, e.g. XAUUSD, BTCUSDT, EURUSD"),
    timeframe: tool.schema.string().optional().describe("Timeframe, e.g. M5, M15, H1 (fetch only)"),
    provider: tool.schema.string().optional().describe("Provider name or 'auto'"),
    limit: tool.schema.number().optional().describe("Candles to fetch (default 1000)"),
  },
  async execute(args) {
    if (args.action === "providers") {
      const result = runCli(["providers"], 60_000)
      return {
        title: "provider availability",
        output: result.ok ? result.stdout : failureMessage(result),
      }
    }

    if (!args.symbol) {
      return { title: "missing symbol", output: "Provide a symbol, e.g. XAUUSD or BTCUSDT." }
    }

    if (args.action === "price") {
      const result = runCli(["price", args.symbol, "-p", args.provider ?? "auto"], 60_000)
      return {
        title: `price ${args.symbol}`,
        output: result.ok ? result.stdout : failureMessage(result),
      }
    }

    const timeframe = args.timeframe ?? "M5"
    const result = runCli(
      [
        "fetch",
        args.symbol,
        "-t",
        timeframe,
        "-p",
        args.provider ?? "auto",
        "--limit",
        String(args.limit ?? 1000),
      ],
      240_000,
    )
    return {
      title: `fetch ${args.symbol} ${timeframe}`,
      output: result.ok ? result.stdout : failureMessage(result),
    }
  },
})
