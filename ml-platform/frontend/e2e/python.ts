import { existsSync } from "node:fs";
import path from "node:path";

export function resolveE2EPython(): string {
  const configured = process.env.E2E_PYTHON?.trim();
  if (configured) return configured;
  if (process.platform !== "win32") return "python3";

  const windowsAppsSegment = `${path.sep}windowsapps${path.sep}`;
  const executable = (process.env.PATH ?? "")
    .split(path.delimiter)
    .filter(Boolean)
    .map((directory) => path.join(directory, "python.exe"))
    .find((candidate) => (
      !candidate.toLowerCase().includes(windowsAppsSegment) && existsSync(candidate)
    ));
  return executable ?? "python";
}
