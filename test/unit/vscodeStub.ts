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
  commands: string[];
  ran: string[];
}

export const state: StubState = { values: {}, rejects: {}, commands: [], ran: [] };

export function resetStub(): void {
  state.values = {};
  state.rejects = {};
  state.commands = [];
  state.ran = [];
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
      inspect<T>(key: string): { globalValue: T | undefined } {
        return { globalValue: state.values[id(section, key)] as T | undefined };
      },
      async update(key: string, value: unknown): Promise<void> {
        const target = id(section, key);
        const rejection = state.rejects[target];
        if (rejection !== undefined) {
          throw new Error(rejection);
        }
        if (value === undefined) {
          delete state.values[target];
        } else {
          state.values[target] = value;
        }
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
  async showInformationMessage(): Promise<undefined> {
    return undefined;
  },
  async showErrorMessage(): Promise<undefined> {
    return undefined;
  },
  async showWarningMessage(): Promise<undefined> {
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
