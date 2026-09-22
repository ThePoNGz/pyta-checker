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
