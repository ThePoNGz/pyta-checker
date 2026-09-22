import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetStub } from './vscodeStub';

const mocks = vi.hoisted(() => ({
  findPython: vi.fn(),
  started: [] as string[],
  stopped: [] as string[],
  stopTimeouts: [] as (number | undefined)[],
}));

// Externalised by vitest, so its own require('vscode') escapes the stub alias.
// extension.ts only needs the State enum from it at runtime.
vi.mock('vscode-languageclient/node', () => ({
  State: { Stopped: 1, Running: 2, Starting: 3, StartFailed: 4 },
}));

vi.mock('../../src/python', () => ({
  findPython: mocks.findPython,
  onInterpreterChanged: async () => undefined,
}));

vi.mock('../../src/client', () => ({
  STATUS_NOTIFICATION: 'pyta/status',
  CHECK_COMMAND: 'pyta.check',
  createClient: (pythonPath: string) => ({
    onNotification: () => undefined,
    onDidChangeState: () => undefined,
    isRunning: () => true,
    start: async () => {
      mocks.started.push(pythonPath);
    },
    stop: async (timeout?: number) => {
      mocks.stopped.push(pythonPath);
      mocks.stopTimeouts.push(timeout);
    },
  }),
  requestCheck: async () => undefined,
}));

vi.mock('../../src/statusBar', () => ({
  StatusBar: class {
    setServerState(): void {
      /* no bar in the stub */
    }
    onStatus(): void {
      /* no bar in the stub */
    }
    dispose(): void {
      /* no bar in the stub */
    }
  },
}));

type Extension = typeof import('../../src/extension');
let extension: Extension;

function fakeContext(): Parameters<Extension['activate']>[0] {
  const store = new Map<string, unknown>();
  return {
    subscriptions: [],
    extensionPath: '/ext',
    globalState: {
      get: (key: string) => store.get(key),
      update: async (key: string, value: unknown) => {
        if (value === undefined) {
          store.delete(key);
        } else {
          store.set(key, value);
        }
      },
    },
  } as unknown as Parameters<Extension['activate']>[0];
}

describe('extension lifecycle', () => {
  beforeEach(async () => {
    resetStub();
    mocks.started.length = 0;
    mocks.stopped.length = 0;
    mocks.stopTimeouts.length = 0;
    mocks.findPython.mockReset();
    // extension.ts keeps the client and restart state at module scope
    vi.resetModules();
    extension = await import('../../src/extension.js');
  });

  it('starts a server on activate and stops it on deactivate', async () => {
    mocks.findPython.mockResolvedValue({ path: 'python' });

    await extension.activate(fakeContext());
    expect(mocks.started).toEqual(['python']);

    await extension.deactivate();
    expect(mocks.stopped).toEqual(['python']);
  });

  it('gives the server long enough to shut its checks down cleanly', async () => {
    // The default is 2s; a clean shutdown with checks in flight measures ~9.4s,
    // and timing out leaves the runner and its mypy children behind.
    mocks.findPython.mockResolvedValue({ path: 'python' });

    await extension.activate(fakeContext());
    await extension.deactivate();

    expect(mocks.stopTimeouts).toEqual([15_000]);
  });

  it('does not start a server when deactivate lands mid-restart', async () => {
    // Interpreter discovery can take seconds. Deactivating while it is in flight
    // must not leave a language server running with nothing owning it.
    let finishDiscovery!: (value: unknown) => void;
    mocks.findPython.mockReturnValue(
      new Promise((resolve) => {
        finishDiscovery = resolve;
      }),
    );

    const activation = extension.activate(fakeContext());
    await Promise.resolve();
    const deactivation = extension.deactivate();
    finishDiscovery({ path: 'python' });
    await activation;
    await deactivation;

    expect(mocks.started).toEqual([]);
  });
});
