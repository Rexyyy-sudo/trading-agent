import { tool } from "@opencode-ai/plugin"
import { failureMessage, runCli } from "../lib/cli"

export const paper_trade = tool({
  description: [
    "Paper-trading account (SIMULATION ONLY - there is no live trading in this project; no real order is ever placed).",
    "Actions: status, history, simulate (replay candles against open positions), open, close.",
    "Account persists at data/paper/account.json. Opening requires a symbol, side and entry (plus size or stop for auto-sizing).",
  ].join(" "),
  args: {
    action: tool.schema
      .enum(["status", "history", "simulate", "open", "close"])
      .describe("What to do"),
    symbol: tool.schema.string().optional().describe("Symbol (simulate/open)"),
    side: tool.schema.enum(["LONG", "SHORT"]).optional().describe("Position side (open)"),
    entry: tool.schema.number().optional().describe("Entry price (open)"),
    stop_loss: tool.schema.number().optional().describe("Stop-loss price (open)"),
    take_profit: tool.schema.number().optional().describe("Take-profit price (open)"),
    size: tool.schema.number().optional().describe("Size in units (open)"),
    risk_pct: tool.schema.number().optional().describe("Risk percent for auto-sizing (open)"),
    position_id: tool.schema.string().optional().describe("Position id (close)"),
    price: tool.schema.number().optional().describe("Exit price (close; default latest)"),
    timeframe: tool.schema.string().optional().describe("Timeframe (simulate/open)"),
    provider: tool.schema.string().optional().describe("Provider name or 'auto' (simulate)"),
    limit: tool.schema.number().optional().describe("Candles to replay (simulate, default 500)"),
  },
  async execute(args) {
    let cliArgs: string[]

    switch (args.action) {
      case "status":
        cliArgs = ["paper", "status"]
        break
      case "history":
        cliArgs = ["paper", "history"]
        break
      case "simulate": {
        if (!args.symbol) {
          return { title: "missing symbol", output: "simulate needs a symbol." }
        }
        cliArgs = [
          "paper",
          "simulate",
          args.symbol,
          "-p",
          args.provider ?? "auto",
          "--limit",
          String(args.limit ?? 500),
        ]
        if (args.timeframe) cliArgs.push("-t", args.timeframe)
        break
      }
      case "open": {
        if (!args.symbol || !args.side || args.entry === undefined) {
          return { title: "missing inputs", output: "open needs symbol, side and entry." }
        }
        cliArgs = [
          "paper",
          "open",
          args.symbol,
          args.side,
          "--entry",
          String(args.entry),
        ]
        if (args.stop_loss !== undefined) cliArgs.push("--sl", String(args.stop_loss))
        if (args.take_profit !== undefined) cliArgs.push("--tp", String(args.take_profit))
        if (args.size !== undefined) cliArgs.push("--size", String(args.size))
        if (args.risk_pct !== undefined) cliArgs.push("--risk-pct", String(args.risk_pct))
        if (args.timeframe) cliArgs.push("--timeframe", args.timeframe)
        cliArgs.push("--note", "opencode tool")
        break
      }
      case "close": {
        if (!args.position_id) {
          return { title: "missing position id", output: "close needs a position_id (see status)." }
        }
        cliArgs = ["paper", "close", args.position_id]
        if (args.price !== undefined) cliArgs.push("--price", String(args.price))
        break
      }
    }

    const result = runCli(cliArgs, 240_000)
    if (!result.ok) {
      return { title: `paper ${args.action} failed`, output: failureMessage(result) }
    }
    const suffix =
      args.action === "open" || args.action === "close"
        ? "\n(Simulated only - no live order was placed.)"
        : ""
    return { title: `paper ${args.action}`, output: `${result.stdout}${suffix}` }
  },
})
