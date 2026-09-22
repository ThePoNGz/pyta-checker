import { describe, expect, it } from 'vitest';
import { IGNORE_ALL, TARGETS, planDisable, planEnable } from '../../src/onlyPytaLogic';

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
});
