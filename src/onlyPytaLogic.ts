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

export function planEnable(current: Snapshot, saved: Snapshot | undefined): { saved: Snapshot; writes: Write[] } {
  return {
    saved: saved ?? current,
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
