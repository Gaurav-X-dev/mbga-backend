import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

declare const process: { env: Record<string, string | undefined>; platform: string };

const BACKEND_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "backend");

function backendPython(): string {
  if (process.env.E2E_BACKEND_PYTHON) return process.env.E2E_BACKEND_PYTHON;
  const candidates =
    process.platform === "win32"
      ? [join(BACKEND_DIR, "venv", "Scripts", "python.exe"), join(BACKEND_DIR, ".venv", "Scripts", "python.exe")]
      : [join(BACKEND_DIR, "venv", "bin", "python"), join(BACKEND_DIR, ".venv", "bin", "python")];
  return candidates.find((candidate) => existsSync(candidate)) ?? "python";
}

/**
 * Removes records created by earlier E2E runs using the backend's guarded cleanup script
 * (local/development/test databases on this computer only; E2E-marked records only).
 */
export function cleanupE2EData(stage: string) {
  if (process.env.E2E_SKIP_CLEANUP === "1") {
    console.log(`[e2e ${stage}] cleanup skipped (E2E_SKIP_CLEANUP=1)`);
    return;
  }
  const output = execFileSync(backendPython(), ["scripts/cleanup_e2e_test_data.py", "--apply"], {
    cwd: BACKEND_DIR,
    encoding: "utf8"
  });
  const summary = output
    .split(/\r?\n/)
    .filter((line: string) => /merchants:|delivery team members:|users to delete:|Nothing to clean|removed/.test(line))
    .map((line: string) => line.trim())
    .join("; ");
  console.log(`[e2e ${stage}] ${summary}`);
}
