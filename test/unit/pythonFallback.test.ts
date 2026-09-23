import { beforeEach, describe, expect, it, vi } from 'vitest';

// findPython keeps the once per session flag at module scope, so both it and the stub
// get re-imported per test.
type Python = typeof import('../../src/python');
type Stub = typeof import('./vscodeStub');
type Log = Parameters<Python['findPython']>[1];

const probes = vi.hoisted(() => ({ table: {} as Record<string, string | Error> }));

vi.mock('node:child_process', () => ({
  execFile: (
    command: string,
    _args: string[],
    _options: unknown,
    callback: (error: Error | null, result?: { stdout: string }) => void,
  ) => {
    const result = probes.table[command];
    if (result === undefined || result instanceof Error) {
      callback(result ?? new Error(`spawn ${command} ENOENT`));
    } else {
      callback(null, { stdout: result });
    }
  },
}));

// No Python extension in a unit test, so findPython falls back to PATH on its own.
vi.mock('@vscode/python-extension', () => ({
  PythonExtension: {
    api: async () => {
      throw new Error('no python extension here');
    },
  },
}));

let python: Python;
let stub: Stub;
const log = {
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
  show: () => undefined,
} as unknown as Log;

beforeEach(async () => {
  vi.resetModules();
  stub = await import('./vscodeStub.js');
  stub.resetStub();
  python = await import('../../src/python.js');
  probes.table = {};
});

describe('falling back from the interpreter in the setting', () => {
  it('says which interpreter failed and why, once per session', async () => {
    // Silently using a different Python is how a student ends up with results from an
    // environment they did not choose and no idea it happened.
    probes.table = { 'C:/gone/python.exe': new Error('spawn C:/gone/python.exe ENOENT'), python: '3.13\n', python3: '3.13\n' };

    const result = await python.findPython('C:/gone/python.exe', log);
    expect(result).not.toHaveProperty('error');

    expect(stub.state.warned).toHaveLength(1);
    expect(stub.state.warned[0]).toContain('C:/gone/python.exe');
    expect(stub.state.warned[0]).toContain('ENOENT');

    await python.findPython('C:/gone/python.exe', log);
    expect(stub.state.warned).toHaveLength(1);
  });

  it('offers Show Output on that warning', async () => {
    probes.table = { 'C:/gone/python.exe': new Error('ENOENT'), python: '3.13\n', python3: '3.13\n' };
    stub.state.warnAnswer = 'Show Output';

    await python.findPython('C:/gone/python.exe', log);

    expect(stub.state.ran).toContain('pythonta.showOutput');
  });

  it('says nothing when the interpreter that failed did not come from the setting', async () => {
    probes.table = { python: new Error('ENOENT'), python3: '3.13\n', py: '3.13\n' };

    await python.findPython('', log);

    expect(stub.state.warned).toEqual([]);
  });

  it('says nothing when the interpreter in the setting works', async () => {
    probes.table = { 'C:/good/python.exe': '3.13\n' };

    await python.findPython('C:/good/python.exe', log);

    expect(stub.state.warned).toEqual([]);
  });
});
