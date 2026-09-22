/** Stand-in for the vscode module so the settings-writing code can run under vitest. */

export enum ConfigurationTarget {
  Global = 1,
  Workspace = 2,
  WorkspaceFolder = 3,
}

export interface StubFolder {
  uri: { toString(): string };
}

interface StubState {
  /** Global values, keyed "section.key". */
  values: Record<string, unknown>;
  /** Keys whose update() throws, mapped to the message VS Code would raise. */
  rejects: Record<string, string>;
  /** Values set at workspace scope, which outrank anything written globally. */
  scoped: Record<string, unknown>;
  /** Values set in one folder's .vscode/settings.json, keyed by folder uri then "section.key". */
  folders: Record<string, Record<string, unknown>>;
  /** The roots of a multi-root workspace; undefined when no folder is open. */
  workspaceFolders: StubFolder[] | undefined;
  commands: string[];
  /** Command callbacks, by id, so a test can invoke what the extension registered. */
  registered: Record<string, (...args: unknown[]) => unknown>;
  ran: string[];
  warned: string[];
  /** Ids of settings an update() actually changed, in order. */
  writes: string[];
  info: string[];
  errors: string[];
  /** What showInformationMessage resolves to. */
  answer: unknown;
  /** What showErrorMessage resolves to. */
  errorAnswer: unknown;
  /** What showWarningMessage resolves to. */
  warnAnswer: unknown;
  /** Runs while showInformationMessage is open, to model a value changing under it. */
  onInfo: (() => void) | undefined;
  /** Runs inside a landed update(), to model the configuration event firing there. */
  onUpdate: ((id: string) => void) | undefined;
}

export const state: StubState = {
  values: {},
  rejects: {},
  scoped: {},
  folders: {},
  workspaceFolders: undefined,
  commands: [],
  registered: {},
  ran: [],
  warned: [],
  writes: [],
  info: [],
  errors: [],
  answer: undefined,
  errorAnswer: undefined,
  warnAnswer: undefined,
  onInfo: undefined,
  onUpdate: undefined,
};

export function resetStub(): void {
  state.values = {};
  state.rejects = {};
  state.scoped = {};
  state.folders = {};
  state.workspaceFolders = undefined;
  state.commands = [];
  state.registered = {};
  state.ran = [];
  state.warned = [];
  state.writes = [];
  state.info = [];
  state.errors = [];
  state.answer = undefined;
  state.errorAnswer = undefined;
  state.warnAnswer = undefined;
  state.onInfo = undefined;
  state.onUpdate = undefined;
}

function id(section: string, key: string): string {
  return `${section}.${key}`;
}

function folderValues(resource: { toString(): string } | undefined): Record<string, unknown> | undefined {
  return resource === undefined ? undefined : state.folders[resource.toString()];
}

export const workspace = {
  get workspaceFolders(): StubFolder[] | undefined {
    return state.workspaceFolders;
  },
  onDidChangeConfiguration(): Disposable {
    return new Disposable();
  },
  getConfiguration(section: string, resource?: { toString(): string }) {
    const folder = folderValues(resource);
    return {
      get<T>(key: string, fallback: T): T {
        // Folder beats workspace beats user, as it does in VS Code.
        const target = id(section, key);
        const value = folder?.[target] ?? state.scoped[target] ?? state.values[target];
        return value === undefined ? fallback : (value as T);
      },
      inspect<T>(key: string): { globalValue: T | undefined; workspaceValue: T | undefined; workspaceFolderValue: T | undefined } {
        return {
          globalValue: state.values[id(section, key)] as T | undefined,
          workspaceValue: state.scoped[id(section, key)] as T | undefined,
          // Only an inspect given a resource can see a folder value.
          workspaceFolderValue: folder?.[id(section, key)] as T | undefined,
        };
      },
      async update(key: string, value: unknown, target?: ConfigurationTarget): Promise<void> {
        const settingId = id(section, key);
        const rejection = state.rejects[settingId];
        if (rejection !== undefined) {
          throw new Error(rejection);
        }
        state.writes.push(settingId);
        const bucket =
          target === ConfigurationTarget.Workspace
            ? state.scoped
            : target === ConfigurationTarget.WorkspaceFolder
              ? (state.folders[resource?.toString() ?? ''] ??= {})
              : state.values;
        if (value === undefined) {
          delete bucket[settingId];
        } else {
          bucket[settingId] = value;
        }
        state.onUpdate?.(settingId);
      },
    };
  },
};

export const commands = {
  async getCommands(): Promise<string[]> {
    return state.commands;
  },
  async executeCommand(command: string): Promise<void> {
    state.ran.push(command);
  },
  registerCommand(id: string, callback: (...args: unknown[]) => unknown): Disposable {
    state.registered[id] = callback;
    return new Disposable();
  },
};

export class Disposable {
  dispose(): void {
    /* nothing to release in the stub */
  }
}

export enum StatusBarAlignment {
  Left = 1,
  Right = 2,
}

export const window = {
  activeTextEditor: undefined,
  async showInformationMessage(message: string): Promise<unknown> {
    state.info.push(message);
    state.onInfo?.();
    return state.answer;
  },
  async showErrorMessage(message: string): Promise<unknown> {
    state.errors.push(message);
    return state.errorAnswer;
  },
  async showWarningMessage(message: string): Promise<unknown> {
    state.warned.push(message);
    return state.warnAnswer;
  },
  createOutputChannel() {
    return {
      info: () => undefined,
      warn: () => undefined,
      error: () => undefined,
      show: () => undefined,
      dispose: () => undefined,
    };
  },
  createStatusBarItem() {
    return {
      text: '',
      tooltip: '',
      command: '',
      show: () => undefined,
      hide: () => undefined,
      dispose: () => undefined,
    };
  },
};

export const Uri = {
  parse(value: string): { toString(): string } {
    return { toString: () => value };
  },
};

export const env = {
  async openExternal(): Promise<boolean> {
    return true;
  },
};
