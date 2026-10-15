import { tool } from "@opencode-ai/plugin"
import { failureMessage, runCli } from "../lib/cli"

interface AnalysisReport {
  symbol?: string
  timeframe?: string
  data_status?: string
  provider?: string
  price?: number | null
  candle_count?: number
  decision?: { signal?: string; bias?: string; reasons?: string[] }
  score?: { score?: number; label?: string; confidence?: number } | null
  entry?: {
    entry_lower?: number
    entry_upper?: number
    stop_loss?: number
    targets?: number[]
    rr_values?: number[]
    model?: string
    confirmation?: string
    invalidation?: string
  } | null
  risk?: { risk_amount?: number; position_units?: number; warnings?: string[] } | null
  warnings?: string[]
  data_reasons?: string[]
}

export const technical_analysis = tool({
  description: [
    "Run the full multi-timeframe market analysis pipeline (trend, structure, support/resistance, liquidity,",
    "momentum, volatility, volume, scoring, LONG/SHORT/WAIT/NO TRADE decision, entry scenario and risk estimate).",
    "Returns the framework's structured JSON report plus a summary. No guarantees, no live trading:",
    "the decision can legitimately be WAIT or NO TRADE. Use market_data if data is missing.",
  ].join(" "),
  args: {
    symbol: tool.schema.string().describe("Symbol, e.g. XAUUSD, BTCUSDT, EURUSD"),
    timeframe: tool.schema.string().optional().describe("Entry timeframe, default M5"),
    timeframes: tool.schema.string().optional().describe("Explicit comma list, e.g. H1,M15,M5"),
    provider: tool.schema.string().optional().describe("Provider name or 'auto'"),
    limit: tool.schema.number().optional().describe("Candles to fetch per timeframe"),
  },
  async execute(args) {
    const cliArgs = ["analyze", args.symbol, "-p", args.provider ?? "auto"]
    if (args.timeframes) {
      cliArgs.push("-T", args.timeframes)
    } else if (args.timeframe) {
      cliArgs.push(args.timeframe)
    }
    if (args.limit) cliArgs.push("--limit", String(args.limit))
    cliArgs.push("--json")

    const result = runCli(cliArgs, 240_000)
    if (!result.ok) {
      return { title: `analysis failed: ${args.symbol}`, output: failureMessage(result) }
    }

    let report: AnalysisReport
    try {
      report = JSON.parse(result.stdout) as AnalysisReport
    } catch {
      return {
        title: `analysis output unparsable: ${args.symbol}`,
        output: result.stdout,
      }
    }

    const decision = report.decision ?? {}
    const lines = [
      `symbol: ${report.symbol} | timeframe: ${report.timeframe} | data: ${report.data_status} (provider: ${report.provider}, candles: ${report.candle_count})`,
      `price: ${report.price ?? "n/a"}`,
      `final status: ${decision.signal ?? "UNKNOWN"} | bias: ${decision.bias ?? "UNKNOWN"}`,
    ]
    if (report.score) {
      lines.push(`score: ${report.score.score}/100 (${report.score.label}) | confidence: ${report.score.confidence}`)
    }
    if (report.entry) {
      const targets = (report.entry.targets ?? []).join(" / ")
      lines.push(
        `entry zone: ${report.entry.entry_lower} - ${report.entry.entry_upper} | stop: ${report.entry.stop_loss} | targets: ${targets} | model: ${report.entry.model}`,
      )
    }
    if (report.risk) {
      lines.push(`risk: amount ${report.risk.risk_amount} | size ${report.risk.position_units} units`)
    }
    const reasons = decision.reasons ?? []
    for (const reason of reasons) lines.push(`reason: ${reason}`)
    for (const warning of report.warnings ?? []) lines.push(`warning: ${warning}`)
    for (const reason of report.data_reasons ?? []) lines.push(`data note: ${reason}`)

    return {
      title: `${report.symbol} ${report.timeframe}: ${decision.signal ?? "?"}`,
      output: `${lines.join("\n")}\n\nFull structured report (exact tool output):\n${JSON.stringify(report, null, 2)}`,
    }
  },
})
