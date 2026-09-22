import * as vscode from 'vscode';
import type { StatusParams } from './client';

export type ServerState = 'starting' | 'running' | 'error';

interface FileStatus {
  state: 'checking' | 'done';
  count: number;
}

export class StatusBar implements vscode.Disposable {
  private readonly item: vscode.StatusBarItem;
  private readonly files = new Map<string, FileStatus>();
  private serverState: ServerState = 'starting';
  private readonly subscriptions: vscode.Disposable[] = [];

  constructor() {
    this.item = vscode.window.createStatusBarItem('pythonta.status', vscode.StatusBarAlignment.Right, 90);
    this.item.name = 'PythonTA';
    this.subscriptions.push(
      vscode.window.onDidChangeActiveTextEditor(() => this.refresh()),
      vscode.workspace.onDidCloseTextDocument((doc) => {
        this.files.delete(doc.uri.toString());
        this.refresh();
      }),
    );
    this.item.show();
    this.refresh();
  }

  setServerState(state: ServerState): void {
    this.serverState = state;
    this.refresh();
  }

  onStatus(params: StatusParams): void {
    this.files.set(vscode.Uri.parse(params.uri).toString(), { state: params.state, count: params.count ?? 0 });
    this.refresh();
  }

  refresh(): void {
    if (this.serverState === 'error') {
      this.set('$(error) PyTA', 'PythonTA server is not running. Click to show the log.', 'pythonta.showOutput', true);
      return;
    }
    if (this.serverState === 'starting') {
      this.set('$(sync~spin) PyTA', 'PythonTA server is starting', 'pythonta.showOutput', false);
      return;
    }
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.document.languageId !== 'python') {
      this.set('PyTA', 'PythonTA Checker: open a Python file', 'pythonta.check', false);
      return;
    }
    const status = this.files.get(editor.document.uri.toString());
    if (!status) {
      this.set('PyTA', 'PythonTA: click to check this file', 'pythonta.check', false);
    } else if (status.state === 'checking') {
      this.set('$(sync~spin) PyTA', 'PythonTA is checking this file', 'pythonta.check', false);
    } else if (status.count === 0) {
      this.set('$(check) PyTA', 'PythonTA found no problems in this file. Click to re-check.', 'pythonta.check', false);
    } else {
      this.set(
        `$(warning) PyTA ${status.count}`,
        `PythonTA found ${status.count} problem${status.count === 1 ? '' : 's'} in this file. Click to re-check.`,
        'pythonta.check',
        false,
      );
    }
  }

  private set(text: string, tooltip: string, command: string, warn: boolean): void {
    this.item.text = text;
    this.item.tooltip = tooltip;
    this.item.command = command;
    this.item.backgroundColor = warn ? new vscode.ThemeColor('statusBarItem.warningBackground') : undefined;
  }

  dispose(): void {
    this.item.dispose();
    for (const sub of this.subscriptions) {
      sub.dispose();
    }
  }
}
