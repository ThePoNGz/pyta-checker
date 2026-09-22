import * as vscode from 'vscode';

let log: vscode.LogOutputChannel | undefined;

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  log = vscode.window.createOutputChannel('PythonTA', { log: true });
  context.subscriptions.push(
    log,
    vscode.commands.registerCommand('pythonta.showOutput', () => log?.show(true)),
  );
  log.info('PythonTA Checker activated');
}

export async function deactivate(): Promise<void> {
  log = undefined;
}
