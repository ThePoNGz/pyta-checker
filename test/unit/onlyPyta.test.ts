import { beforeEach, describe, expect, it } from 'vitest';
import { SAVED_KEY, applyOnlyPyta } from '../../src/onlyPyta';
import { resetStub, state } from './vscodeStub';

type Context = Parameters<typeof applyOnlyPyta>[1];
type Log = Parameters<typeof applyOnlyPyta>[2];

const UNREGISTERED =
  'Unable to write to User Settings because basedpyright.analysis.ignore is not a registered configuration.';

function fakeContext(store = new Map<string, unknown>()): Context {
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

/** A second window on the same globalState that read it before the first window wrote. */
function staleContext(shared: Context): Context {
  return {
    globalState: {
      get: () => undefined,
      update: (key: string, value: unknown) => shared.globalState.update(key, value),
    },
  } as unknown as Context;
}

const log = { info: () => undefined, warn: () => undefined } as unknown as Log;

describe('applyOnlyPyta', () => {
  beforeEach(resetStub);

  it('keeps the snapshot when a restore is refused because the extension is gone', async () => {
    state.values['basedpyright.analysis.ignore'] = ['src/generated'];
    const context = fakeContext();

    await applyOnlyPyta(true, context, log);
    expect(state.values['basedpyright.analysis.ignore']).toEqual(['**']);

    // basedpyright is uninstalled, so VS Code refuses writes to its settings, but the
    // ignore-all we wrote is still sitting in settings.json.
    state.rejects['basedpyright.analysis.ignore'] = UNREGISTERED;
    await applyOnlyPyta(false, context, log);

    // python restored cleanly so we no longer owe it anything. Only the refused
    // entry stays behind.
    expect(context.globalState.get(SAVED_KEY)).toEqual({ basedpyright: ['src/generated'] });
  });

  it('re-snapshots a setting the user changed while Only-PythonTA was on', async () => {
    state.values['python.analysis.ignore'] = ['a'];
    const context = fakeContext();
    await applyOnlyPyta(true, context, log);

    // the user edits it by hand, then a window reload re-applies enable
    state.values['python.analysis.ignore'] = ['new'];
    await applyOnlyPyta(true, context, log);
    await applyOnlyPyta(false, context, log);

    expect(state.values['python.analysis.ignore']).toEqual(['new']);
  });

  it('leaves a setting alone when it no longer holds our sentinel', async () => {
    const context = fakeContext();
    await applyOnlyPyta(true, context, log);

    // whatever the snapshot still claims, the value on disk belongs to the user now
    state.values['python.analysis.ignore'] = ['mine'];
    await applyOnlyPyta(false, context, log);

    expect(state.values['python.analysis.ignore']).toEqual(['mine']);
  });

  it('does not claim a setting whose enable write was refused', async () => {
    // basedpyright is not installed, so our ignore-all never lands on it. Recording
    // it anyway means a later disable "restores" a setting we never touched.
    state.rejects['basedpyright.analysis.ignore'] = UNREGISTERED;
    const context = fakeContext();

    await applyOnlyPyta(true, context, log);
    expect(context.globalState.get(SAVED_KEY)).toEqual({ python: null });

    // the student installs basedpyright and configures it themselves
    delete state.rejects['basedpyright.analysis.ignore'];
    state.values['basedpyright.analysis.ignore'] = ['mine'];
    await applyOnlyPyta(false, context, log);

    expect(state.values['basedpyright.analysis.ignore']).toEqual(['mine']);
  });

  it('keeps an entry owed from an earlier cycle when a new write is refused', async () => {
    state.values['basedpyright.analysis.ignore'] = ['b'];
    const context = fakeContext();

    await applyOnlyPyta(true, context, log);
    state.rejects['basedpyright.analysis.ignore'] = UNREGISTERED;
    await applyOnlyPyta(false, context, log);
    expect(context.globalState.get(SAVED_KEY)).toEqual({ basedpyright: ['b'] });

    await applyOnlyPyta(true, context, log);

    expect(context.globalState.get(SAVED_KEY)).toEqual({ basedpyright: ['b'], python: null });
  });

  it('does not overwrite a value the user changed after a partial restore', async () => {
    state.values['python.analysis.ignore'] = ['a'];
    state.values['basedpyright.analysis.ignore'] = ['b'];
    const context = fakeContext();

    await applyOnlyPyta(true, context, log);
    state.rejects['basedpyright.analysis.ignore'] = UNREGISTERED;
    await applyOnlyPyta(false, context, log);
    expect(state.values['python.analysis.ignore']).toEqual(['a']);

    // python belongs to the user again, so what they set now is what a later disable
    // owes them, not the value we snapshotted two toggles ago.
    state.values['python.analysis.ignore'] = ['c'];
    await applyOnlyPyta(true, context, log);
    await applyOnlyPyta(false, context, log);

    expect(state.values['python.analysis.ignore']).toEqual(['c']);
  });

  it('records nothing in a cycle that had nothing to write', async () => {
    // Another window, or another machine, already wrote the sentinel. This one
    // overwrote nothing, so it owes nothing and has no business recording a debt.
    state.values['python.analysis.ignore'] = ['mine'];
    await applyOnlyPyta(true, fakeContext(), log);
    const secondWindow = fakeContext();

    await applyOnlyPyta(true, secondWindow, log);

    expect(secondWindow.globalState.get(SAVED_KEY)).toBeUndefined();
  });

  it('leaves the user value recoverable when a window that wrote nothing shares the snapshot', async () => {
    state.values['python.analysis.ignore'] = ['mine'];
    const store = new Map<string, unknown>();
    const context = fakeContext(store);
    await applyOnlyPyta(true, context, log);

    // The second window writes through to the same storage. Recording "absent" here
    // throws away the only copy of the value the user had.
    await applyOnlyPyta(true, staleContext(context), log);
    await applyOnlyPyta(false, context, log);

    expect(state.values['python.analysis.ignore']).toEqual(['mine']);
  });

  it('still treats a sentinel it did not write as absent when the cycle writes something', async () => {
    // Settings Sync or a reinstall can leave one setting already holding the sentinel
    // with nothing recorded against it. Disabling must remove it, not restore it.
    state.values['basedpyright.analysis.ignore'] = ['**'];
    const context = fakeContext();

    await applyOnlyPyta(true, context, log);
    expect(context.globalState.get(SAVED_KEY)).toEqual({ python: null, basedpyright: null });
    await applyOnlyPyta(false, context, log);

    expect(state.values['basedpyright.analysis.ignore']).toBeUndefined();
  });

  it('removes a sentinel that no snapshot accounts for at all', async () => {
    // Both settings already hold it and nothing was recorded anywhere, so the enable
    // writes nothing. Disabling has to clear it or the other linters stay silent.
    state.values['python.analysis.ignore'] = ['**'];
    state.values['basedpyright.analysis.ignore'] = ['**'];
    const context = fakeContext();

    await applyOnlyPyta(true, context, log);
    await applyOnlyPyta(false, context, log);

    expect(state.values['python.analysis.ignore']).toBeUndefined();
    expect(state.values['basedpyright.analysis.ignore']).toBeUndefined();
  });

  it('says so when a workspace setting outranks the global write', async () => {
    // Writing globally reports success but a workspace value wins, so problems from
    // the other server stay on screen and the toggle looks broken.
    state.scoped['basedpyright.analysis.ignore'] = ['src/generated'];

    await applyOnlyPyta(true, fakeContext(), log);

    expect(state.warned.join(' ')).toContain('basedpyright.analysis.ignore');
  });

  it('drops the snapshot once every restore write lands', async () => {
    state.values['basedpyright.analysis.ignore'] = ['src/generated'];
    const context = fakeContext();

    await applyOnlyPyta(true, context, log);
    await applyOnlyPyta(false, context, log);

    expect(context.globalState.get(SAVED_KEY)).toBeUndefined();
    expect(state.values['basedpyright.analysis.ignore']).toEqual(['src/generated']);
    expect(state.values['python.analysis.ignore']).toBeUndefined();
  });

  it('still restarts the other servers when the snapshot cannot be written', async () => {
    state.commands = ['python.analysis.restartLanguageServer', 'basedpyright.restartserver'];
    const store = new Map<string, unknown>();
    let calls = 0;
    const context = {
      globalState: {
        get: (key: string) => store.get(key),
        update: async (key: string, value: unknown) => {
          calls += 1;
          if (calls > 1) {
            throw new Error('storage is unavailable');
          }
          store.set(key, value);
        },
      },
    } as unknown as Context;

    await applyOnlyPyta(true, context, log);

    expect(state.ran).toContain('basedpyright.restartserver');
  });
});
