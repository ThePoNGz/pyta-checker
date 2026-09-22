import { describe, expect, it } from 'vitest';
import {
  IGNORE_ALL,
  TARGETS,
  isUnregisteredSettingError,
  newlyClaimed,
  planDisable,
  planEnable,
} from '../../src/onlyPytaLogic';

describe('TARGETS', () => {
  it('covers pylance (via the python extension) and basedpyright with verified command ids', () => {
    expect(TARGETS).toEqual([
      { section: 'python', key: 'analysis.ignore', restartCommand: 'python.analysis.restartLanguageServer' },
      { section: 'basedpyright', key: 'analysis.ignore', restartCommand: 'basedpyright.restartserver' },
    ]);
  });
});

describe('planEnable', () => {
  it('snapshots current values the first time and writes ignore-all to both', () => {
    const plan = planEnable({ python: ['src/generated'], basedpyright: null }, undefined);
    expect(plan.saved).toEqual({ python: ['src/generated'], basedpyright: null });
    expect(plan.writes).toEqual([
      { section: 'python', key: 'analysis.ignore', value: IGNORE_ALL },
      { section: 'basedpyright', key: 'analysis.ignore', value: IGNORE_ALL },
    ]);
  });

  it('keeps an existing snapshot so re-enabling never saves our own ignore-all', () => {
    const plan = planEnable({ python: IGNORE_ALL, basedpyright: IGNORE_ALL }, { python: null, basedpyright: ['x'] });
    expect(plan.saved).toEqual({ python: null, basedpyright: ['x'] });
  });

  it('never snapshots our own ignore-all when the snapshot is missing', () => {
    // Settings Sync carries settings between machines but not globalState, and
    // uninstall drops globalState while leaving settings behind. Recording the
    // sentinel here would make it the value we "restore" to, permanently.
    const plan = planEnable({ python: IGNORE_ALL, basedpyright: ['**'] }, undefined);
    expect(plan.saved).toEqual({ python: null, basedpyright: null });
  });

  it('still snapshots a real user value that happens to sit beside a sentinel', () => {
    const plan = planEnable({ python: ['mine'], basedpyright: IGNORE_ALL }, undefined);
    expect(plan.saved).toEqual({ python: ['mine'], basedpyright: null });
  });

  it('records the current value for a section a partial snapshot does not cover', () => {
    // A partial snapshot means an earlier restore only half landed. The sections
    // it no longer covers were handed back to the user, so their value now is the
    // one we owe them.
    const plan = planEnable({ python: ['changed'], basedpyright: IGNORE_ALL }, { basedpyright: ['b'] });
    expect(plan.saved).toEqual({ python: ['changed'], basedpyright: ['b'] });
  });
});

describe('planDisable', () => {
  it('restores saved values and removes keys that were absent', () => {
    expect(planDisable({ python: ['src/generated'], basedpyright: null })).toEqual([
      { section: 'python', key: 'analysis.ignore', value: ['src/generated'] },
      { section: 'basedpyright', key: 'analysis.ignore', value: undefined },
    ]);
  });

  it('writes nothing when there is no snapshot', () => {
    expect(planDisable(undefined)).toEqual([]);
  });

  it('leaves alone a section the snapshot does not cover', () => {
    expect(planDisable({ basedpyright: ['b'] })).toEqual([
      { section: 'basedpyright', key: 'analysis.ignore', value: ['b'] },
    ]);
  });
});

describe('isUnregisteredSettingError', () => {
  it('recognises a target extension simply not being installed', () => {
    const error = new Error(
      'Unable to write to User Settings because basedpyright.analysis.ignore is not a registered configuration.',
    );
    expect(isUnregisteredSettingError(error)).toBe(true);
  });

  it('does not excuse a real write failure', () => {
    // A read-only or malformed settings.json must keep the snapshot alive.
    expect(isUnregisteredSettingError(new Error('EACCES: permission denied, open settings.json'))).toBe(false);
  });
});

describe('newlyClaimed', () => {
  it('claims only sections an earlier cycle was not already owed', () => {
    expect(newlyClaimed({ basedpyright: ['b'] }, { basedpyright: ['b'], python: ['p'] })).toEqual(new Set(['python']));
  });

  it('claims every section when there is no snapshot yet', () => {
    expect(newlyClaimed(undefined, { python: null, basedpyright: null })).toEqual(new Set(['python', 'basedpyright']));
  });
});
