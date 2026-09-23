import { beforeEach, describe, expect, it, vi } from 'vitest';

// The session state these tests cover (the once per session warning, the state the
// toggle has already applied) lives at module scope, so both modules get re-imported
// per test. The stub included, or the module under test would see a second copy.
type OnlyPyta = typeof import('../../src/onlyPyta');
type Stub = typeof import('./vscodeStub');
type Context = Parameters<OnlyPyta['applyOnlyPyta']>[1];
type Log = Parameters<OnlyPyta['applyOnlyPyta']>[2];

let onlyPyta: OnlyPyta;
let stub: Stub;

const log = { info: () => undefined, warn: () => undefined, error: () => undefined } as unknown as Log;
const IGNORE_ALL = ['**'];
const RESTARTS = ['python.analysis.restartLanguageServer', 'basedpyright.restartserver'];

function fakeContext(): Context {
  const store = new Map<string, unknown>();
  return {
    globalState: {
      get: (key: string) => store.get(key),
      update: async (key: string, value: unknown) => {
        if (value === undefined) {
          store.delete(key);
        } else {
          store.set(key, value);
        }
      },
    },
  } as unknown as Context;
}

beforeEach(async () => {
  vi.resetModules();
  stub = await import('./vscodeStub.js');
  onlyPyta = await import('../../src/onlyPyta.js');
  stub.resetStub();
  stub.state.commands = [...RESTARTS];
});

describe('re-applying an enable that is already in place', () => {
  it('writes nothing and restarts nothing when both settings already hold the sentinel', async () => {
    // Activation applies again on every window open. Rewriting settings that already
    // hold the sentinel restarts Pylance from scratch every time, forever.
    const context = fakeContext();
    await onlyPyta.applyOnlyPyta(true, context, log);
    stub.state.writes = [];
    stub.state.ran = [];

    await onlyPyta.applyOnlyPyta(true, context, log);

    expect(stub.state.writes).toEqual([]);
    expect(stub.state.ran).toEqual([]);
  });

  it('restarts the other servers when a write actually lands', async () => {
    await onlyPyta.applyOnlyPyta(true, fakeContext(), log);

    expect(stub.state.ran).toEqual(RESTARTS);
  });

  it('restarts nothing when disabling has nothing to restore', async () => {
    await onlyPyta.applyOnlyPyta(false, fakeContext(), log);

    expect(stub.state.ran).toEqual([]);
  });

  it('warns about a workspace override at most once per session', async () => {
    stub.state.scoped['basedpyright.analysis.ignore'] = ['src/generated'];
    const context = fakeContext();

    await onlyPyta.applyOnlyPyta(true, context, log);
    await onlyPyta.applyOnlyPyta(false, context, log);
    await onlyPyta.applyOnlyPyta(true, context, log);

    expect(stub.state.warned).toHaveLength(1);
  });

  it('stays quiet about a workspace override when activation is the trigger', async () => {
    stub.state.scoped['basedpyright.analysis.ignore'] = ['src/generated'];

    await onlyPyta.applyOnlyPyta(true, fakeContext(), log, { silent: true });

    expect(stub.state.warned).toEqual([]);
  });
});

describe('toggleOnlyPyta', () => {
  it('reports the real failure with a Show Output action', async () => {
    stub.state.rejects['python.analysis.ignore'] = 'EACCES: permission denied, open settings.json';
    stub.state.errorAnswer = 'Show Output';

    await onlyPyta.toggleOnlyPyta(fakeContext(), log);

    expect(stub.state.info).toEqual([]);
    expect(stub.state.errors.join(' ')).toContain('PythonTA');
    expect(stub.state.ran).toContain('pythonta.showOutput');
  });

  it('reports success only once the writes have landed', async () => {
    await onlyPyta.toggleOnlyPyta(fakeContext(), log);

    expect(stub.state.values['python.analysis.ignore']).toEqual(IGNORE_ALL);
    expect(stub.state.info.join(' ')).toContain('only PythonTA');
  });

  it('says a workspace setting is blocking instead of claiming success', async () => {
    stub.state.scoped['python.analysis.ignore'] = ['src/generated'];

    await onlyPyta.toggleOnlyPyta(fakeContext(), log);

    expect(stub.state.info).toEqual([]);
    expect(stub.state.warned.join(' ')).toContain('python.analysis.ignore');
  });

  it('does not let the configuration listener apply the same toggle again', async () => {
    const context = fakeContext();
    await onlyPyta.toggleOnlyPyta(context, log);

    // extension.ts routes the onDidChangeConfiguration event here. The toggle has
    // already applied this value, so there is nothing left to do.
    expect(await onlyPyta.syncOnlyPyta(true, context, log)).toBeUndefined();
  });

  it('does not apply twice when the configuration event arrives during the write', async () => {
    // VS Code fires onDidChangeConfiguration while update() is still in flight, so
    // the listener can reach the apply before the toggle does.
    const context = fakeContext();
    const listener: Promise<unknown>[] = [];
    stub.state.onUpdate = (id) => {
      if (id === 'pythonta.hideOtherPythonDiagnostics') {
        listener.push(onlyPyta.syncOnlyPyta(true, context, log));
      }
    };

    await onlyPyta.toggleOnlyPyta(context, log);

    expect(await Promise.all(listener)).toEqual([undefined]);
  });

  it('applies a change made outside the toggle', async () => {
    const context = fakeContext();

    expect(await onlyPyta.syncOnlyPyta(true, context, log)).toBeDefined();
    expect(stub.state.values['python.analysis.ignore']).toEqual(IGNORE_ALL);
  });
});

describe('maybePromptFirstRun', () => {
  it('does not ask again on a second machine where the setting synced across', async () => {
    // hideOtherPythonDiagnostics travels with Settings Sync but the prompted flag in
    // globalState does not.
    stub.state.values['pythonta.hideOtherPythonDiagnostics'] = true;
    const context = fakeContext();
    stub.state.answer = 'No';

    await onlyPyta.maybePromptFirstRun(context);

    expect(stub.state.info).toEqual([]);
    expect(stub.state.values['pythonta.hideOtherPythonDiagnostics']).toBe(true);
    expect(context.globalState.get(onlyPyta.PROMPTED_KEY)).toBe(true);
  });

  it('turns the setting off when the user answers No to a prompt they enabled meanwhile', async () => {
    stub.state.answer = 'No';
    stub.state.onInfo = () => {
      stub.state.values['pythonta.hideOtherPythonDiagnostics'] = true;
    };

    await onlyPyta.maybePromptFirstRun(fakeContext());

    expect(stub.state.values['pythonta.hideOtherPythonDiagnostics']).toBe(false);
  });

  it('writes nothing when No leaves the setting as it already was', async () => {
    stub.state.answer = 'No';

    await onlyPyta.maybePromptFirstRun(fakeContext());

    expect(stub.state.writes).toEqual([]);
  });
});

describe('toggle off under a workspace override', () => {
  it('says the problems stay hidden instead of claiming they are visible again', async () => {
    // A workspace analysis.ignore outranks the restored user value in both directions,
    // so the global restore lands and the other server keeps ignoring.
    const context = fakeContext();
    await onlyPyta.toggleOnlyPyta(context, log);
    stub.state.info.length = 0;
    stub.state.scoped['python.analysis.ignore'] = IGNORE_ALL;

    await onlyPyta.toggleOnlyPyta(context, log);

    expect(stub.state.values['pythonta.hideOtherPythonDiagnostics']).toBe(false);
    expect(stub.state.info).toEqual([]);
    expect(stub.state.warned.join(' ')).toContain('python.analysis.ignore');
  });
});

describe('a value in a scope that outranks the user setting', () => {
  // Our global write only matters if it changes the effective value, so what blocks
  // depends on the direction. The sentinel hides everything, anything else does not.
  it('does not block an enable with a workspace copy of our sentinel, which hides them too', async () => {
    stub.state.scoped['python.analysis.ignore'] = IGNORE_ALL;

    const outcome = await onlyPyta.applyOnlyPyta(true, fakeContext(), log);

    expect(outcome.blocked).toEqual([]);
    expect(stub.state.warned).toEqual([]);
  });

  it('blocks an enable with any other workspace value, which keeps them visible', async () => {
    stub.state.scoped['python.analysis.ignore'] = ['src/generated'];

    const outcome = await onlyPyta.applyOnlyPyta(true, fakeContext(), log);

    expect(outcome.blocked).toEqual(['python.analysis.ignore']);
  });

  it('blocks a disable with a workspace copy of our sentinel, which keeps them hidden', async () => {
    stub.state.scoped['python.analysis.ignore'] = IGNORE_ALL;

    const outcome = await onlyPyta.applyOnlyPyta(false, fakeContext(), log);

    expect(outcome.blocked).toEqual(['python.analysis.ignore']);
  });

  it('does not block a disable with any other workspace value, which shows them anyway', async () => {
    stub.state.scoped['python.analysis.ignore'] = ['src/generated'];

    const outcome = await onlyPyta.applyOnlyPyta(false, fakeContext(), log);

    expect(outcome.blocked).toEqual([]);
    expect(stub.state.warned).toEqual([]);
  });

  it('sees a folder value in a multi-root workspace, which a resource-less inspect misses', async () => {
    stub.state.workspaceFolders = [{ uri: stub.Uri.parse('file:///a') }, { uri: stub.Uri.parse('file:///b') }];
    stub.state.folders['file:///b'] = { 'basedpyright.analysis.ignore': ['src/generated'] };

    const outcome = await onlyPyta.applyOnlyPyta(true, fakeContext(), log);

    expect(outcome.blocked).toEqual(['basedpyright.analysis.ignore']);
  });
});
