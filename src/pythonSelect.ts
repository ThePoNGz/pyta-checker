import { MIN_PYTHON, VERSION_PROBE, formatVersion, isSupported, parsePythonVersion, type PythonVersion } from './pythonVersion';

export type Origin = 'setting' | 'python-extension' | 'path';

export interface Candidate {
  path: string;
  origin: Origin;
}

export interface PythonInfo {
  path: string;
  version: PythonVersion;
  origin: Origin;
}

export type Probe = (command: string, args: string[]) => Promise<string>;

export function pathCandidates(platform: NodeJS.Platform): Candidate[] {
  const names = platform === 'win32' ? ['python', 'python3', 'py'] : ['python3', 'python'];
  return names.map((path) => ({ path, origin: 'path' as const }));
}

export async function selectPython(candidates: Candidate[], probe: Probe): Promise<PythonInfo | { error: string }> {
  const attempts: string[] = [];
  for (const candidate of candidates) {
    let version: PythonVersion | undefined;
    try {
      version = parsePythonVersion(await probe(candidate.path, ['-c', VERSION_PROBE]));
    } catch {
      version = undefined;
    }
    if (isSupported(version)) {
      return { path: candidate.path, version, origin: candidate.origin };
    }
    attempts.push(version ? `${candidate.path} (Python ${formatVersion(version)}, too old)` : `${candidate.path} (not runnable)`);
  }
  return {
    error: `No Python ${MIN_PYTHON[0]}.${MIN_PYTHON[1]} or newer was found. Tried: ${attempts.join('; ') || 'nothing'}`,
  };
}
