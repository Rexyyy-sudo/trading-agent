import { existsSync } from "node:fs"
import { spawnSync } from "node:child_process"
import path from "node:path"

const LIB_DIR = path.dirname(new URL(import.meta.url).pathname)

export const PROJECT_ROOT = path.resolve(LIB_DIR, "..", "..")

function pythonBin(): string {
  const unix = path.join(PROJECT_ROOT, ".venv", "bin", "python")
  if (existsSync(unix)) return unix
  const win = path.join(PROJECT_ROOT, ".venv", "Scripts", "python.exe")
  if (existsSync(win)) return win
  return "python3"
}

export interface CliResult {
  ok: boolean
  stdout: string
  stderr: string
  command: string
}

function launch(args: string[], timeoutMs: number, env?: Record<string, string>): CliResult {
  const python = pythonBin()
  const result = spawnSync(python, args, {
    cwd: PROJECT_ROOT,
    encoding: "utf8",
    timeout: timeoutMs,
    maxBuffer: 8 * 1024 * 1024,
    env: env ? { ...process.env, ...env } : process.env,
  })
  return {
    ok: result.status === 0,
    stdout: (result.stdout ?? "").trim(),
    stderr: (result.stderr ?? "").trim(),
    command: [python, ...args].join(" "),
  }
}

export function runCli(args: string[], timeoutMs = 180_000): CliResult {
  return launch(["-m", "src.main", ...args], timeoutMs)
}

export function runPython(code: string, env?: Record<string, string>, timeoutMs = 60_000): CliResult {
  return launch(["-c", code], timeoutMs, env)
}

export function failureMessage(result: CliResult): string {
  return [
    `command failed: ${result.command}`,
    result.stderr ? `stderr:\n${result.stderr}` : "",
    result.stdout ? `stdout:\n${result.stdout}` : "",
    "Hint: run the market_data tool with action \"providers\" to see which data sources are available.",
    "Never invent prices or indicator values - report the failure instead.",
  ]
    .filter(Boolean)
    .join("\n\n")
}
