import { beforeEach, describe, expect, it } from 'vitest';
import { SAVED_KEY, applyOnlyPyta } from '../../src/onlyPyta';
import { resetStub, state } from './vscodeStub';

type Context = Parameters<typeof applyOnlyPyta>[1];
type Log = Parameters<typeof applyOnlyPyta>[2];

const UNREGISTERED =
  'Unable to write to User Settings because basedpyright.analysis.ignore is not a registered configuration.';

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

const log = { info: () => undefined, warn: () => undefined } as unknown as Log;

describe('applyOnlyPyta', () => {
  beforeEach(resetStub);

  it('keeps the snapshot when a restore is refused because the extension is gone', async () => {
    state.values['basedpyright.analysis.ignore'] = ['src/generated'];
    const context = fakeContext();

    await applyOnlyPyta(true, context, log);
    expect(state.values['basedpyright.analysis.ignore']).toEqual(['**']);

    // basedpyright is uninstalled, so VS Code refuses writes to its settings -
    // but the ignore-all we wrote is still sitting in the user's settings.json.
    state.rejects['basedpyright.analysis.ignore'] = UNREGISTERED;
    await applyOnlyPyta(false, context, log);

    // python restored cleanly, so we no longer owe it anything; only the refused
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

    // whatever the snapshot still claims, the value on disk is the user's now
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

    // python is the user's again, so what they set now is what a later disable owes
    // them - not the value we snapshotted two toggles ago.
    state.values['python.analysis.ignore'] = ['c'];
    await applyOnlyPyta(true, context, log);
    await applyOnlyPyta(false, context, log);

    expect(state.values['python.analysis.ignore']).toEqual(['c']);
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
});
