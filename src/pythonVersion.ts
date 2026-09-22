export const MIN_PYTHON: readonly [number, number] = [3, 10];
export const VERSION_PROBE = "import sys; print('%d.%d' % sys.version_info[:2])";

export interface PythonVersion {
  major: number;
  minor: number;
}

export function parsePythonVersion(output: string): PythonVersion | undefined {
  const match = /^\s*(\d+)\.(\d+)\s*$/.exec(output);
  if (!match) {
    return undefined;
  }
  return { major: Number(match[1]), minor: Number(match[2]) };
}

export function isSupported(v: PythonVersion | undefined): v is PythonVersion {
  if (!v) {
    return false;
  }
  return v.major > MIN_PYTHON[0] || (v.major === MIN_PYTHON[0] && v.minor >= MIN_PYTHON[1]);
}

export function formatVersion(v: PythonVersion): string {
  return `${v.major}.${v.minor}`;
}
