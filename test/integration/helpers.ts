import * as vscode from 'vscode';

export const SOURCE = 'PythonTA';

export function codeOf(diagnostic: vscode.Diagnostic): string {
  const code = diagnostic.code;
  if (code && typeof code === 'object') {
    return String(code.value);
  }
  return String(code ?? '');
}

export function pytaDiagnostics(uri: vscode.Uri): vscode.Diagnostic[] {
  return vscode.languages.getDiagnostics(uri).filter((d) => d.source === SOURCE);
}

export function waitForPytaDiagnostics(
  uri: vscode.Uri,
  predicate: (diagnostics: vscode.Diagnostic[]) => boolean,
  timeoutMs = 120_000,
): Promise<vscode.Diagnostic[]> {
  return new Promise((resolve, reject) => {
    const check = (): boolean => {
      const diagnostics = pytaDiagnostics(uri);
      if (predicate(diagnostics)) {
        cleanup();
        resolve(diagnostics);
        return true;
      }
      return false;
    };
    const subscription = vscode.languages.onDidChangeDiagnostics((event) => {
      if (event.uris.some((u) => u.toString() === uri.toString())) {
        check();
      }
    });
    const timer = setTimeout(() => {
      cleanup();
      const last = pytaDiagnostics(uri).map((d) => `${codeOf(d)}: ${d.message}`);
      reject(new Error(`timed out waiting for PythonTA diagnostics on ${uri.fsPath}; last: ${JSON.stringify(last)}`));
    }, timeoutMs);
    function cleanup(): void {
      clearTimeout(timer);
      subscription.dispose();
    }
    check();
  });
}

export function waitForDiagnosticsChange(uri: vscode.Uri, timeoutMs = 120_000): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      subscription.dispose();
      reject(new Error(`timed out waiting for a diagnostics change on ${uri.fsPath}`));
    }, timeoutMs);
    const subscription = vscode.languages.onDidChangeDiagnostics((event) => {
      if (event.uris.some((u) => u.toString() === uri.toString())) {
        clearTimeout(timer);
        subscription.dispose();
        resolve();
      }
    });
  });
}

export async function openFixture(name: string): Promise<vscode.Uri> {
  const folder = vscode.workspace.workspaceFolders?.[0];
  if (!folder) {
    throw new Error('no workspace folder; .vscode-test.mjs must set workspaceFolder');
  }
  const uri = vscode.Uri.joinPath(folder.uri, name);
  const document = await vscode.workspace.openTextDocument(uri);
  await vscode.window.showTextDocument(document);
  return uri;
}
