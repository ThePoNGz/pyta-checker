import { describe, expect, it } from 'vitest';
import { pathCandidates, selectPython, type Candidate, type Probe } from '../../src/pythonSelect';

function fakeProbe(table: Record<string, string | Error>): Probe {
  return async (command) => {
    const result = table[command];
    if (result === undefined || result instanceof Error) {
      throw result ?? new Error(`spawn ${command} ENOENT`);
    }
    return result;
  };
}

describe('selectPython', () => {
  it('returns the first candidate that is 3.10 or newer, in order', async () => {
    const candidates: Candidate[] = [
      { path: 'C:/old/python.exe', origin: 'setting' },
      { path: 'C:/good/python.exe', origin: 'python-extension' },
      { path: 'python', origin: 'path' },
    ];
    const result = await selectPython(
      candidates,
      fakeProbe({ 'C:/old/python.exe': '3.9\n', 'C:/good/python.exe': '3.13\n', python: '3.14\n' }),
    );
    expect(result).toEqual({ path: 'C:/good/python.exe', version: { major: 3, minor: 13 }, origin: 'python-extension' });
  });

  it('skips candidates that fail to run', async () => {
    const result = await selectPython(
      [{ path: 'python', origin: 'path' }, { path: 'python3', origin: 'path' }],
      fakeProbe({ python: new Error('ENOENT'), python3: '3.12' }),
    );
    expect(result).toMatchObject({ path: 'python3' });
  });

  it('reports every attempt when nothing qualifies', async () => {
    const result = await selectPython(
      [{ path: 'py', origin: 'path' }, { path: 'python', origin: 'path' }],
      fakeProbe({ py: '3.8\n', python: new Error('ENOENT') }),
    );
    expect(result).toHaveProperty('error');
    const error = (result as { error: string }).error;
    expect(error).toContain('py (Python 3.8, too old)');
    expect(error).toContain('python (not runnable)');
  });
});

describe('pathCandidates', () => {
  it('prefers py launcher last on windows and python3 first elsewhere', () => {
    expect(pathCandidates('win32').map((c) => c.path)).toEqual(['python', 'python3', 'py']);
    expect(pathCandidates('linux').map((c) => c.path)).toEqual(['python3', 'python']);
    expect(pathCandidates('darwin').map((c) => c.path)).toEqual(['python3', 'python']);
  });
});
