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

/** Our own sentinel is not a user value: record it as absent so disable removes it. */
function asOriginal(value: unknown): unknown {
  return value === undefined || isIgnoreAll(value) ? null : value;
}

/**
 * A section present in the snapshot is one we have overwritten and still owe back.
 * Sections already restored are absent, so their current value is the user's own.
 */
export function planEnable(current: Snapshot, saved: Snapshot | undefined): { saved: Snapshot; writes: Write[] } {
  const next: Snapshot = { ...saved };
  for (const target of TARGETS) {
    if (!(target.section in next)) {
      next[target.section] = asOriginal(current[target.section]);
    }
  }
  return {
    saved: next,
    writes: TARGETS.map((t) => ({ section: t.section, key: t.key, value: IGNORE_ALL })),
  };
}

/** Sections this cycle claims for the first time; an earlier cycle's debt is not ours to drop. */
export function newlyClaimed(saved: Snapshot | undefined, next: Snapshot): Set<string> {
  return new Set(Object.keys(next).filter((section) => saved === undefined || !(section in saved)));
}

export function planDisable(saved: Snapshot | undefined): Write[] {
  if (!saved) {
    return [];
  }
  return TARGETS.filter((t) => t.section in saved).map((t) => {
    const previous = saved[t.section];
    return { section: t.section, key: t.key, value: previous === null ? undefined : previous };
  });
}
