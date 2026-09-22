export const IGNORE_ALL: readonly string[] = ['**'];

export interface Target {
  section: string;
  key: string;
  restartCommand: string;
}

export const TARGETS: readonly Target[] = [
  { section: 'python', key: 'analysis.ignore', restartCommand: 'python.analysis.restartLanguageServer' },
  { section: 'basedpyright', key: 'analysis.ignore', restartCommand: 'basedpyright.restartserver' },
];

export type Snapshot = Record<string, unknown>;

export interface Write {
  section: string;
  key: string;
  value: unknown;
}

/** VS Code rejects writes to a setting no installed extension has registered. */
export function isUnregisteredSettingError(error: unknown): boolean {
  return String(error).includes('not a registered configuration');
}

function isIgnoreAll(value: unknown): boolean {
  return (
    Array.isArray(value) &&
    value.length === IGNORE_ALL.length &&
    value.every((entry, index) => entry === IGNORE_ALL[index])
  );
}

/**
 * A section present in the snapshot is one we have overwritten and still owe back.
 *
 * Anything on disk that is not our sentinel came from the user, so it replaces what
 * we recorded - they may have edited it since, with Only-PythonTA on or off. Our own
 * sentinel says nothing about their value, so it never overwrites a recorded one, and
 * stands for "absent" when there is nothing recorded yet.
 */
export function planEnable(current: Snapshot, saved: Snapshot | undefined): { saved: Snapshot; writes: Write[] } {
  const next: Snapshot = { ...saved };
  for (const target of TARGETS) {
    const value = current[target.section];
    if (!isIgnoreAll(value)) {
      next[target.section] = value === undefined ? null : value;
    } else if (!(target.section in next)) {
      next[target.section] = null;
    }
  }
  return {
    saved: next,
    // A section already holding the sentinel needs no write: re-writing it on every
    // window open restarts the other language server for no change.
    writes: TARGETS.filter((t) => !isIgnoreAll(current[t.section])).map((t) => ({
      section: t.section,
      key: t.key,
      value: IGNORE_ALL,
    })),
  };
}

/** Sections this cycle claims for the first time; an earlier cycle's debt is not ours to drop. */
export function newlyClaimed(saved: Snapshot | undefined, next: Snapshot): Set<string> {
  return new Set(Object.keys(next).filter((section) => saved === undefined || !(section in saved)));
}

/**
 * Restore only settings that still hold our sentinel. A section holding anything
 * else was either never overwritten by us or has been changed since, so the value
 * on disk is the user's and not ours to write over - whatever the snapshot claims.
 */
export function planDisable(saved: Snapshot | undefined, current: Snapshot): Write[] {
  if (!saved) {
    return [];
  }
  return TARGETS.filter((t) => t.section in saved && isIgnoreAll(current[t.section])).map((t) => {
    const previous = saved[t.section];
    return { section: t.section, key: t.key, value: previous === null ? undefined : previous };
  });
}
