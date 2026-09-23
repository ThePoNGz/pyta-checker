// Extension entry point. Owns the language client lifecycle, the commands and the status bar.
import * as vscode from 'vscode';
import { State, type LanguageClient } from 'vscode-languageclient/node';
import { createClient, requestCheck } from './client';
import { STATUS_NOTIFICATION, type StatusParams } from './client';
import { SAVED_KEY, applyOnlyPyta, maybeShowOnlyPytaNotice, syncOnlyPyta, toggleOnlyPyta, type ApplyOutcome } from './onlyPyta';
import { findPython, onInterpreterChanged } from './python';
import { getSettings } from './settings';
import { StatusBar } from './statusBar';

/** The server kills its own runner sub process trees on its way out. A clean shutdown
 * take 9.4s, way more than default which is 2s. */
const STOP_TIMEOUT = 15_000;
/** How long we wait for a restarting client to reach a state it can be stopped in. */
const SETTLE_TIMEOUT = 3_000;

let client: LanguageClient | undefined;
let log: vscode.LogOutputChannel;
let restarting: Promise<void> | undefined;
let restartPending = false;
let disposed = false;
let statusBar: StatusBar;
/** Clients that refused to stop. Each one still owns a Python server process. */
const unstopped: LanguageClient[] = [];

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  disposed = false;
  // The setting this snapshot describes is application scoped and travels with Settings
  // Sync. Without this the machine it lands on restores the wrong value.
  context.globalState.setKeysForSync([SAVED_KEY]);
  log = vscode.window.createOutputChannel('PythonTA', { log: true });
  statusBar = new StatusBar();
  context.subscriptions.push(statusBar);
  context.subscriptions.push(
    log,
    vscode.commands.registerCommand('pythonta.showOutput', () => log.show(true)),
    vscode.commands.registerCommand('pythonta.restart', () => restartServer(context)),
    vscode.commands.registerCommand('pythonta.check', () => checkActiveFile()),
    vscode.commands.registerCommand('pythonta.toggleOnlyPyta', () => toggleOnlyPyta(context, log)),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration('pythonta.interpreter') || event.affectsConfiguration('pythonta.importStrategy')) {
        void restartServer(context);
      }
      if (event.affectsConfiguration('pythonta.hideOtherPythonDiagnostics')) {
        syncOnlyPyta(getSettings().hideOtherPythonDiagnostics, context, log).catch((error) => log.error(`Only-PythonTA update failed: ${String(error)}`));
      }
    }),
  );
  const watcher = await onInterpreterChanged(() => {
    log.info('Python interpreter changed; restarting PythonTA server');
    void restartServer(context);
  }, log);
  if (watcher) {
    context.subscriptions.push(watcher);
  }
  await restartServer(context);
  const settings = getSettings();
  // The notice only goes up for a hide that actually landed, so it needs what the
  // apply came back with.
  let outcome: ApplyOutcome | undefined;
  if (settings.hideOtherPythonDiagnostics || context.globalState.get(SAVED_KEY)) {
    try {
      outcome = await applyOnlyPyta(settings.hideOtherPythonDiagnostics, context, log, { silent: true });
    } catch (error) {
      log.error(`Only-PythonTA setup failed: ${String(error)}`);
    }
  }
  maybeShowOnlyPytaNotice(context, outcome).catch((error) => log.error(`Only-PythonTA notice failed: ${String(error)}`));
}

export async function deactivate(): Promise<void> {
  disposed = true;
  restartPending = false;
  // A restart in flight might still be waiting on interpreter discovery. Let it finish
  // and bail out, or it starts a server after deactivation with nothing left to stop it.
  try {
    await restarting;
  } catch {
    // restartServer logs its own failures
  }
  // Last chance, a client left behind by a restart would outlive the window. We take
  // the list before stopping the current one so a fresh failure is not retried twice.
  const orphans = unstopped.splice(0);
  await stopServer();
  for (const orphan of orphans) {
    await stopClient(orphan);
  }
}

async function startServer(context: vscode.ExtensionContext): Promise<void> {
  const settings = getSettings();
  const python = await findPython(settings.interpreter, log);
  if (disposed) {
    return;
  }
  if ('error' in python) {
    statusBar.setServerState('error');
    showPythonError(python.error);
    return;
  }
  const next = createClient(python.path, context.extensionPath, log);
  client = next;
  statusBar.setServerState('starting');
  next.onNotification(STATUS_NOTIFICATION, (params: StatusParams) => statusBar.onStatus(params));
  next.onDidChangeState((event) => {
    if (client !== next) {
      return;
    }
    if (event.newState === State.Running) {
      statusBar.setServerState('running');
    } else if (event.newState === State.StartFailed || event.newState === State.Stopped) {
      statusBar.setServerState('error');
    }
  });
  try {
    await next.start();
    log.info('PythonTA server started');
  } catch (error) {
    statusBar.setServerState('error');
    log.error(`PythonTA server failed to start: ${String(error)}`);
    void vscode.window.showErrorMessage('PythonTA server failed to start.', 'Show Output').then((choice) => {
      if (choice) {
        log.show(true);
      }
    });
  }
}

async function stopServer(): Promise<void> {
  const current = client;
  client = undefined;
  if (!current) {
    return;
  }
  if (!(await stopClient(current)) && !unstopped.includes(current)) {
    // Dropping it here leaves the Python server running with nothing holding it.
    unstopped.push(current);
  }
}

/**
 * vscode-languageclient refuses to stop a client that is not Running, even while its
 * own auto restart after a server crash is in flight. So we wait for the state to
 * settle and try once more before giving up on it.
 *
 * @param current the client to shut down, running or not
 * @returns true if it stopped or had no process to stop, false if it refused twice
 */
async function stopClient(current: LanguageClient): Promise<boolean> {
  for (let attempt = 0; attempt < 2; attempt += 1) {
    // A client whose server never came up owns no process, so nothing to stop and
    // nothing to wait for.
    if (current.state === State.StartFailed) {
      return true;
    }
    try {
      await current.stop(STOP_TIMEOUT);
      return true;
    } catch (error) {
      log.warn(`Error stopping PythonTA server: ${String(error)}`);
    }
    if (attempt === 0) {
      await settled(current);
    }
  }
  log.warn('The PythonTA server could not be stopped.');
  return false;
}

/** Resolves when the client finishes settling. Because stop() blocks during startup and or when the timeout hits */
function settled(current: LanguageClient): Promise<void> {
  if (hasSettled(current.state)) {
    return Promise.resolve();
  }
  return new Promise<void>((resolve) => {
    const timer = setTimeout(() => finish(), SETTLE_TIMEOUT);
    const subscription = current.onDidChangeState((event) => {
      if (hasSettled(event.newState)) {
        finish();
      }
    });
    function finish(): void {
      clearTimeout(timer);
      subscription.dispose();
      resolve();
    }
  });
}

function hasSettled(state: State): boolean {
  return state === State.Running || state === State.Stopped || state === State.StartFailed;
}

async function restartServer(context: vscode.ExtensionContext): Promise<void> {
  if (disposed) {
    return;
  }
  if (restarting) {
    restartPending = true;
    return restarting;
  }
  restarting = (async () => {
    await stopServer();
    await startServer(context);
  })();
  try {
    await restarting;
  } finally {
    // If this fail we still need to reset the flags. If we dont, a restart mid run
    // would get stuck queued and then the next run it will trigger twice.
    restarting = undefined;
    const pending = restartPending;
    restartPending = false;
    if (pending && !disposed) {
      await restartServer(context);
    }
  }
}

async function checkActiveFile(): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.document.languageId !== 'python' || editor.document.uri.scheme !== 'file') {
    void vscode.window.showInformationMessage('PythonTA: open a saved Python file first.');
    return;
  }
  if (editor.document.isDirty) {
    await editor.document.save();
  }
  if (!client?.isRunning()) {
    void vscode.window.showWarningMessage('PythonTA server is not running.', 'Show Output').then((choice) => {
      if (choice) {
        log.show(true);
      }
    });
    return;
  }
  try {
    await requestCheck(client, editor.document.uri);
  } catch (error) {
    log.error(`PythonTA check failed: ${String(error)}`);
    void vscode.window.showErrorMessage('PythonTA check failed.', 'Show Output').then((choice) => {
      if (choice) {
        log.show(true);
      }
    });
  }
}

function showPythonError(message: string): void {
  void vscode.window
    .showErrorMessage(`PythonTA: ${message}`, 'Select Interpreter', 'How to install Python')
    .then((choice) => {
      if (choice === 'Select Interpreter') {
        void vscode.commands.executeCommand('python.setInterpreter');
      } else if (choice === 'How to install Python') {
        void vscode.env.openExternal(vscode.Uri.parse('https://www.python.org/downloads/'));
      }
    });
}
