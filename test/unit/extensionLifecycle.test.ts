import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SAVED_KEY } from '../../src/onlyPyta';

// vi.resetModules() below gives extension.ts a fresh copy of the vscode stub, so we
// have to re-import the stub with it or the test writes to a second, unused copy.
type Stub = typeof import('./vscodeStub');
let stub: Stub;

const State = { Stopped: 1, Running: 2, Starting: 3, StartFailed: 4 };

const mocks = vi.hoisted(() => ({
  findPython: vi.fn(),
  started: [] as string[],
  stopped: [] as string[],
  stopTimeouts: [] as (number | undefined)[],
  /** Set by a test that needs a client it can drive, otherwise the plain fake below. */
  makeClient: undefined as ((pythonPath: string) => unknown) | undefined,
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
  createClient: (pythonPath: string) =>
    mocks.makeClient?.(pythonPath) ?? {
      state: 2,
      onNotification: () => undefined,
      onDidChangeState: () => ({ dispose: () => undefined }),
      isRunning: () => true,
      start: async () => {
        mocks.started.push(pythonPath);
      },
      stop: async (timeout?: number) => {
        mocks.stopped.push(pythonPath);
        mocks.stopTimeouts.push(timeout);
      },
    },
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
const synced: string[][] = [];

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
      setKeysForSync: (keys: readonly string[]) => {
        synced.push([...keys]);
      },
    },
  } as unknown as Parameters<Extension['activate']>[0];
}

interface StateEvent {
  oldState: number;
  newState: number;
}

/**
 * A client that refuses to stop unless it is Running, the way vscode-languageclient
 * does while its own auto restart after a server crash is still in flight.
 */
function drivableClient(pythonPath: string) {
  const listeners = new Set<(event: StateEvent) => void>();
  const client = {
    state: State.Stopped,
    stopCalls: 0,
    startFails: false,
    onNotification: () => undefined,
    isRunning: () => client.state === State.Running,
    onDidChangeState(listener: (event: StateEvent) => void) {
      listeners.add(listener);
      return { dispose: () => listeners.delete(listener) };
    },
    async start(): Promise<void> {
      if (client.startFails) {
        client.transition(State.StartFailed);
        throw new Error('the server failed to start');
      }
      mocks.started.push(pythonPath);
      client.transition(State.Running);
    },
    async stop(timeout?: number): Promise<void> {
      client.stopCalls += 1;
      if (client.state !== State.Running) {
        throw new Error(`Client is not running and can't be stopped. It's current state is: ${client.state}`);
      }
      mocks.stopped.push(pythonPath);
      mocks.stopTimeouts.push(timeout);
      client.transition(State.Stopped);
    },
    transition(newState: number): void {
      const oldState = client.state;
      client.state = newState;
      for (const listener of [...listeners]) {
        listener({ oldState, newState });
      }
    },
  };
  return client;
}

type Drivable = ReturnType<typeof drivableClient>;

/** Lets every queued microtask and resolved-promise chain run. */
function flush(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

beforeEach(async () => {
  mocks.started.length = 0;
  mocks.stopped.length = 0;
  mocks.stopTimeouts.length = 0;
  mocks.makeClient = undefined;
  synced.length = 0;
  mocks.findPython.mockReset();
  // extension.ts keeps the client and restart state at module scope
  vi.resetModules();
  stub = await import('./vscodeStub.js');
  stub.resetStub();
  extension = await import('../../src/extension.js');
});

describe('extension lifecycle', () => {
  it('starts a server on activate and stops it on deactivate', async () => {
    mocks.findPython.mockResolvedValue({ path: 'python' });

    await extension.activate(fakeContext());
    expect(mocks.started).toEqual(['python']);

    await extension.deactivate();
    expect(mocks.stopped).toEqual(['python']);
  });

  it('gives the server long enough to shut its checks down cleanly', async () => {
    // The default is 2s but a clean shutdown with checks in flight takes about 9.4s.
    // Timing out leaves the runner and its mypy children behind.
    mocks.findPython.mockResolvedValue({ path: 'python' });

    await extension.activate(fakeContext());
    await extension.deactivate();

    expect(mocks.stopTimeouts).toEqual([15_000]);
  });

  it('lets the saved ignore snapshot travel with the setting it describes', async () => {
    // hideOtherPythonDiagnostics is application-scoped and syncs between machines.
    // Without the snapshot, the machine it lands on restores the wrong value.
    mocks.findPython.mockResolvedValue({ path: 'python' });

    await extension.activate(fakeContext());

    expect(synced).toEqual([[SAVED_KEY]]);
  });

  it('tells the user once that Only-PythonTA is hiding the other problems', async () => {
    // Only-PythonTA is on by default, so the first window says so instead of asking.
    mocks.findPython.mockResolvedValue({ path: 'python' });
    const context = fakeContext();

    await extension.activate(context);
    await flush();
    expect(stub.state.info.join(' ')).toContain('only PythonTA');

    stub.state.info.length = 0;
    await extension.activate(context);
    await flush();

    expect(stub.state.info).toEqual([]);
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

describe('stopping a client that refuses to stop', () => {
  beforeEach(() => {
    mocks.findPython.mockResolvedValue({ path: 'python' });
  });

  it('waits for the state to settle and retries the stop once', async () => {
    let client!: Drivable;
    mocks.makeClient = (pythonPath) => (client = drivableClient(pythonPath));
    await extension.activate(fakeContext());
    // The server crashed and the client is restarting itself, so stop() throws.
    client.transition(State.Starting);

    const deactivation = extension.deactivate();
    await flush();
    client.transition(State.Running);
    await deactivation;

    expect(client.stopCalls).toBe(2);
    expect(mocks.stopped).toEqual(['python']);
  });

  it('does not wait on a client whose server never came up', async () => {
    // startServer swallows the failure and leaves the client StartFailed. There is no
    // process behind it, so a restart must not stall waiting for it to settle.
    const clients: Drivable[] = [];
    mocks.makeClient = (pythonPath) => {
      const client = drivableClient(pythonPath);
      client.startFails = clients.length === 0;
      clients.push(client);
      return client;
    };
    await extension.activate(fakeContext());

    await stub.state.registered['pythonta.restart']?.();

    expect(clients[0].stopCalls).toBe(0);
    expect(mocks.started).toEqual(['python']);
  });

  it('stops a client left behind by a restart when the window closes', async () => {
    vi.useFakeTimers();
    try {
      const clients: Drivable[] = [];
      mocks.makeClient = (pythonPath) => {
        const client = drivableClient(pythonPath);
        clients.push(client);
        return client;
      };
      await extension.activate(fakeContext());
      const first = clients[0];
      first.transition(State.Starting);

      // A restart now builds a second client. The first one owns a Python process
      // that nothing else will ever stop.
      const restart = stub.state.registered['pythonta.restart']?.();
      await vi.advanceTimersByTimeAsync(5_000);
      await restart;
      expect(clients).toHaveLength(2);
      expect(mocks.stopped).toEqual([]);

      first.transition(State.Running);
      const deactivation = extension.deactivate();
      await vi.advanceTimersByTimeAsync(5_000);
      await deactivation;

      expect(mocks.stopped).toEqual(['python', 'python']);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('a restart that fails', () => {
  it('runs the pending restart once, not twice on the next one', async () => {
    // The first restart rejects. The one requested while it was in flight still owes
    // a run, and must not be left queued behind the restart after it.
    let failDiscovery!: (error: Error) => void;
    mocks.findPython.mockReturnValueOnce(
      new Promise((_resolve, reject) => {
        failDiscovery = reject;
      }),
    );
    mocks.findPython.mockResolvedValue({ path: 'python' });

    const activation = extension.activate(fakeContext()).catch(() => undefined);
    await flush();
    // Callers waiting on the restart in flight see its rejection too.
    void Promise.resolve(stub.state.registered['pythonta.restart']?.()).catch(() => undefined);
    failDiscovery(new Error('interpreter discovery failed'));
    await activation;

    expect(mocks.started).toEqual(['python']);

    mocks.started.length = 0;
    await stub.state.registered['pythonta.restart']?.();

    expect(mocks.started).toEqual(['python']);
  });
});
