import * as vscode from 'vscode';
import { State, type LanguageClient } from 'vscode-languageclient/node';
import { createClient, requestCheck } from './client';
import { STATUS_NOTIFICATION, type StatusParams } from './client';
import { findPython, onInterpreterChanged } from './python';
import { getSettings } from './settings';
import { StatusBar } from './statusBar';

let client: LanguageClient | undefined;
let log: vscode.LogOutputChannel;
let restarting: Promise<void> | undefined;
let statusBar: StatusBar;

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  log = vscode.window.createOutputChannel('PythonTA', { log: true });
  statusBar = new StatusBar();
  context.subscriptions.push(statusBar);
  context.subscriptions.push(
    log,
    vscode.commands.registerCommand('pythonta.showOutput', () => log.show(true)),
    vscode.commands.registerCommand('pythonta.restart', () => restartServer(context)),
    vscode.commands.registerCommand('pythonta.check', () => checkActiveFile()),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration('pythonta.interpreter') || event.affectsConfiguration('pythonta.importStrategy')) {
        void restartServer(context);
      }
    }),
  );
  await startServer(context);
  const watcher = await onInterpreterChanged(() => {
    log.info('Python interpreter changed; restarting PythonTA server');
    void restartServer(context);
  }, log);
  if (watcher) {
    context.subscriptions.push(watcher);
  }
}

export async function deactivate(): Promise<void> {
  await stopServer();
}

async function startServer(context: vscode.ExtensionContext): Promise<void> {
  const settings = getSettings();
  const python = await findPython(settings.interpreter, log);
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
  if (current) {
    try {
      await current.stop();
    } catch (error) {
      log.warn(`Error stopping PythonTA server: ${String(error)}`);
    }
  }
}

async function restartServer(context: vscode.ExtensionContext): Promise<void> {
  if (restarting) {
    return restarting;
  }
  restarting = (async () => {
    await stopServer();
    await startServer(context);
  })();
  try {
    await restarting;
  } finally {
    restarting = undefined;
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
  await requestCheck(client, editor.document.uri);
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
