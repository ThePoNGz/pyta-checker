/** Stand-in for the vscode module so the settings-writing code can run under vitest. */

export enum ConfigurationTarget {
  Global = 1,
  Workspace = 2,
  WorkspaceFolder = 3,
}

interface StubState {
  /** Global values, keyed "section.key". */
  values: Record<string, unknown>;
  /** Keys whose update() throws, mapped to the message VS Code would raise. */
  rejects: Record<string, string>;
  /** Values set at workspace scope, which outrank anything written globally. */
  scoped: Record<string, unknown>;
  commands: string[];
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
  /** Runs while showInformationMessage is open, to model a value changing under it. */
  onInfo: (() => void) | undefined;
  /** Runs inside a landed update(), to model the configuration event firing there. */
  onUpdate: ((id: string) => void) | undefined;
}

export const state: StubState = {
  values: {},
  rejects: {},
  scoped: {},
  commands: [],
  ran: [],
  warned: [],
  writes: [],
  info: [],
  errors: [],
  answer: undefined,
  errorAnswer: undefined,
  onInfo: undefined,
  onUpdate: undefined,
};

export function resetStub(): void {
  state.values = {};
  state.rejects = {};
  state.scoped = {};
  state.commands = [];
  state.ran = [];
  state.warned = [];
  state.writes = [];
  state.info = [];
  state.errors = [];
  state.answer = undefined;
  state.errorAnswer = undefined;
  state.onInfo = undefined;
  state.onUpdate = undefined;
}

function id(section: string, key: string): string {
  return `${section}.${key}`;
}

export const workspace = {
  onDidChangeConfiguration(): Disposable {
    return new Disposable();
  },
  getConfiguration(section: string) {
    return {
      get<T>(key: string, fallback: T): T {
        const value = state.values[id(section, key)];
        return value === undefined ? fallback : (value as T);
      },
      inspect<T>(key: string): { globalValue: T | undefined; workspaceValue: T | undefined; workspaceFolderValue: T | undefined } {
        return {
          globalValue: state.values[id(section, key)] as T | undefined,
          workspaceValue: state.scoped[id(section, key)] as T | undefined,
          workspaceFolderValue: undefined,
        };
      },
      async update(key: string, value: unknown): Promise<void> {
        const target = id(section, key);
        const rejection = state.rejects[target];
        if (rejection !== undefined) {
          throw new Error(rejection);
        }
        state.writes.push(target);
        if (value === undefined) {
          delete state.values[target];
        } else {
          state.values[target] = value;
        }
        state.onUpdate?.(target);
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
  registerCommand(): Disposable {
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
  async showWarningMessage(message: string): Promise<undefined> {
    state.warned.push(message);
    return undefined;
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
