// The planning half of Only-PythonTA. Works out what to write and what to hand back,
// with no vscode API involved so it stays testable on its own.

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

/**
 * What the settings held before we overwrote them, keyed by section.
 *
 * A section is in here only while we still owe it back. The value is whatever the user
 * had, or null when they had nothing set.
 */
export type Snapshot = Record<string, unknown>;

/**
 * One setting write we plan to make.
 *
 * Fields:
 *   section: config section of the target extension, like python or basedpyright
 *   key: setting name inside that section
 *   value: what to write, undefined clears the setting
 */
export interface Write {
  section: string;
  key: string;
  value: unknown;
}

/** VS Code rejects writes to a setting no installed extension has registered. */
export function isUnregisteredSettingError(error: unknown): boolean {
  return String(error).includes('not a registered configuration');
}

export function isIgnoreAll(value: unknown): boolean {
  return (
    Array.isArray(value) &&
    value.length === IGNORE_ALL.length &&
    value.every((entry, index) => entry === IGNORE_ALL[index])
  );
}

/**
 * A section present in the snapshot is one we have overwritten and still owe back.
 *
 * Anything on disk that is not our sentinel came from the user, so it replaces what we
 * recorded, they might have edited it since with Only-PythonTA on or off. Our own
 * sentinel says nothing about their value, so it never overwrites a recorded one, and
 * stands for "absent" when there is nothing recorded yet.
 *
 * @param current what the global settings hold right now, per section
 * @param saved the snapshot an earlier cycle left behind, if there is one
 * @returns the snapshot to record next, and the writes that hide the other problems
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
    // A section already holding the sentinel needs no write. Rewriting it on every
    // window open restarts the other language server for no change.
    writes: TARGETS.filter((t) => !isIgnoreAll(current[t.section])).map((t) => ({
      section: t.section,
      key: t.key,
      value: IGNORE_ALL,
    })),
  };
}

/**
 * Sections this cycle claims for the first time. A debt from an earlier cycle is not
 * ours to drop.
 *
 * @param saved the snapshot as it stood before this cycle
 * @param next the snapshot this cycle is about to record
 */
export function newlyClaimed(saved: Snapshot | undefined, next: Snapshot): Set<string> {
  return new Set(Object.keys(next).filter((section) => saved === undefined || !(section in saved)));
}

/**
 * Restore only settings that still hold our sentinel. A section holding anything else
 * was either never overwritten by us or has changed since, so the value on disk belongs
 * to the user and is not ours to write over, whatever the snapshot claims.
 *
 * A section holding the sentinel with nothing recorded against it is one no window ever
 * recorded a value for, so a reinstall or Settings Sync carrying the setting alone. The
 * sentinel is never a value we owe back, so it comes out and the setting is left absent.
 *
 * @param saved the snapshot recorded when Only-PythonTA was turned on
 * @param current what the global settings hold right now, per section
 * @returns the writes that hand the original values back
 */
export function planDisable(saved: Snapshot | undefined, current: Snapshot): Write[] {
  return TARGETS.filter((t) => isIgnoreAll(current[t.section])).map((t) => {
    const previous = saved?.[t.section] ?? null;
    return { section: t.section, key: t.key, value: previous === null ? undefined : previous };
  });
}
