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
function withoutSentinel(current: Snapshot): Snapshot {
  const cleaned: Snapshot = {};
  for (const [section, value] of Object.entries(current)) {
    cleaned[section] = isIgnoreAll(value) ? null : value;
  }
  return cleaned;
}

export function planEnable(current: Snapshot, saved: Snapshot | undefined): { saved: Snapshot; writes: Write[] } {
  return {
    saved: saved ?? withoutSentinel(current),
    writes: TARGETS.map((t) => ({ section: t.section, key: t.key, value: IGNORE_ALL })),
  };
}

export function planDisable(saved: Snapshot | undefined): Write[] {
  if (!saved) {
    return [];
  }
  return TARGETS.map((t) => {
    const previous = saved[t.section];
    return { section: t.section, key: t.key, value: previous === null ? undefined : previous };
  });
}
