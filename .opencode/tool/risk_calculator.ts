import { tool } from "@opencode-ai/plugin"
import { failureMessage, runCli, runPython } from "../lib/cli"

const MANUAL_CODE = [
  "import json, os",
  "from src.risk.calculator import RiskInput, calculate_risk",
  "payload = json.loads(os.environ['RISK_INPUT'])",
  "result = calculate_risk(RiskInput(**payload), max_risk_pct=2.0)",
  "print(json.dumps(result.as_dict(), default=str, indent=2))",
].join("\n")

export const risk_calculator = tool({
  description: [
    "Position sizing and risk/reward math for the trading-agent framework.",
    "mode=setup (default): reuse the latest analysis' entry zone, stop and targets for a symbol and compute sizing.",
    "mode=manual: give balance, risk_pct, entry, stop and optional targets explicitly.",
    "All output is an ESTIMATE for education; it is not financial advice and guarantees nothing.",
  ].join(" "),
  args: {
    mode: tool.schema.enum(["setup", "manual"]).optional().describe("setup (default) or manual"),
    symbol: tool.schema.string().optional().describe("Symbol (setup mode)"),
    timeframe: tool.schema.string().optional().describe("Entry timeframe, default M5 (setup mode)"),
    provider: tool.schema.string().optional().describe("Provider name or 'auto' (setup mode)"),
    balance: tool.schema.number().optional().describe("Account balance (manual mode)"),
    risk_pct: tool.schema.number().optional().describe("Risk percent per trade (manual mode)"),
    entry: tool.schema.number().optional().describe("Entry price (manual mode)"),
    stop: tool.schema.number().optional().describe("Stop-loss price (manual mode)"),
    targets: tool.schema.array(tool.schema.number()).optional().describe("Target prices (manual mode)"),
  },
  async execute(args) {
    if ((args.mode ?? "setup") === "manual") {
      const required = [args.balance, args.risk_pct, args.entry, args.stop]
      if (required.some((value) => value === undefined)) {
        return {
          title: "missing inputs",
          output: "manual mode needs balance, risk_pct, entry and stop (targets optional).",
        }
      }
      const payload = {
        balance: args.balance,
        risk_pct: args.risk_pct,
        entry: args.entry,
        stop: args.stop,
        targets: args.targets ?? [],
      }
      const result = runPython(MANUAL_CODE, { RISK_INPUT: JSON.stringify(payload) })
      return {
        title: "manual risk estimate",
        output: result.ok ? result.stdout : failureMessage(result),
      }
    }

    if (!args.symbol) {
      return { title: "missing symbol", output: "setup mode needs a symbol (or use mode=manual)." }
    }
    const cliArgs = ["analyze", args.symbol, "-p", args.provider ?? "auto", "--json"]
    if (args.timeframe) cliArgs.splice(2, 0, args.timeframe)
    const result = runCli(cliArgs, 240_000)
    if (!result.ok) {
      return { title: `analysis failed: ${args.symbol}`, output: failureMessage(result) }
    }
    let report: {
      symbol?: string
      data_status?: string
      decision?: { signal?: string }
      entry?: unknown
      risk?: unknown
      warnings?: string[]
    }
    try {
      report = JSON.parse(result.stdout)
    } catch {
      return { title: "unparsable analysis output", output: result.stdout }
    }
    const payload = {
      symbol: report.symbol,
      data_status: report.data_status,
      signal: report.decision?.signal,
      entry: report.entry ?? "no entry scenario (framework did not produce one)",
      risk: report.risk ?? "no risk estimate (no entry scenario)",
      warnings: report.warnings ?? [],
    }
    return {
      title: `risk setup: ${report.symbol} ${report.decision?.signal ?? "?"}`,
      output: JSON.stringify(payload, null, 2),
    }
  },
})
