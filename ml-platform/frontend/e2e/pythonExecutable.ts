import { existsSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";

export function resolveE2ePython(
  environment: NodeJS.ProcessEnv = process.env,
): string {
  const configured = environment.ML_PLATFORM_PYTHON?.trim();
  if (configured) {
    return configured;
  }
  if (process.platform !== "win32") {
    return "python3";
  }
  const localWindowsPython = path.join(homedir(), "miniconda3", "python.exe");
  return existsSync(localWindowsPython) ? localWindowsPython : "python";
}
