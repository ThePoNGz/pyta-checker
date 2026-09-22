import * as assert from 'node:assert';
import * as vscode from 'vscode';
import { codeOf, openFixture, pytaDiagnostics, waitForPytaDiagnostics } from './helpers';

suite('PythonTA Checker', () => {
  suiteSetup(async () => {
    const extension = vscode.extensions.getExtension('ThePoNGz.pyta-checker');
    assert.ok(extension, 'extension not found; check publisher/name in package.json');
    await extension.activate();
  });

  test('honors the embedded check_all config', async () => {
    const uri = await openFixture('course_style.py');
    const diagnostics = await waitForPytaDiagnostics(uri, (d) => d.length > 0);
    const codes = diagnostics.map(codeOf);
    assert.ok(codes.includes('E9989'), `expected E9989 in ${codes}`);
    assert.ok(!codes.includes('E9999'), `E9999 must not appear when extra-imports allows random: ${codes}`);
    assert.ok(!codes.includes('E9998'), `E9998 must not appear when allowed-io allows roll: ${codes}`);
    const pep8 = diagnostics.find((d) => codeOf(d) === 'E9989');
    assert.ok(pep8);
    assert.strictEqual(pep8.severity, vscode.DiagnosticSeverity.Error);
    assert.strictEqual(pep8.range.start.line, 11);
    const code = pep8.code;
    assert.ok(code && typeof code === 'object', 'code should carry a docs link');
    assert.ok(code.target.toString().endsWith('#e9989'), code.target.toString());
  });

  test('reports forbidden imports when there is no embedded config', async () => {
    const uri = await openFixture('no_config.py');
    const diagnostics = await waitForPytaDiagnostics(uri, (d) => d.some((x) => codeOf(x) === 'E9999'));
    const codes = diagnostics.map(codeOf);
    assert.ok(codes.includes('E9999'), `expected E9999 in ${codes}`);
    assert.ok(codes.includes('E9998'), `expected E9998 (forbidden IO) in ${codes}`);
    assert.ok(diagnostics.every((d) => d.source === 'PythonTA'));
  });

  test('reports a syntax error as E0001', async () => {
    const uri = await openFixture('syntax_error.py');
    const diagnostics = await waitForPytaDiagnostics(uri, (d) => d.length > 0);
    assert.deepStrictEqual(diagnostics.map(codeOf), ['E0001']);
    assert.strictEqual(diagnostics[0].range.start.line, 3);
  });

  test('the check command re-runs PythonTA on the active file', async function () {
    this.timeout(240_000);
    const config = vscode.workspace.getConfiguration('pythonta');
    const previousRunOnSave = config.inspect<boolean>('runOnSave')?.globalValue;
    await config.update('runOnSave', false, vscode.ConfigurationTarget.Global);
    const uri = await openFixture('no_config.py');
    const document = await vscode.workspace.openTextDocument(uri);
    const originalText = document.getText();
    // no_config.py already has an E9989 on `total=0`, so every assertion below is
    // scoped to the lines this test appends.
    const lastLine = document.lineCount;
    const isAppendedPep8 = (d: vscode.Diagnostic): boolean =>
      codeOf(d) === 'E9989' && d.range.start.line >= lastLine;
    try {
      await waitForPytaDiagnostics(uri, (d) => d.some((x) => codeOf(x) === 'E9999'));
      assert.ok(!pytaDiagnostics(uri).some(isAppendedPep8), 'fixture must start without a pep8 error past its last line');

      const edit = new vscode.WorkspaceEdit();
      edit.insert(uri, new vscode.Position(lastLine, 0), '\n\nBROKEN=1\n');
      assert.ok(await vscode.workspace.applyEdit(edit));
      await vscode.window.showTextDocument(document);
      await vscode.commands.executeCommand('pythonta.check');

      const diagnostics = await waitForPytaDiagnostics(uri, (d) => d.some(isAppendedPep8));
      const pep8 = diagnostics.find(isAppendedPep8);
      assert.ok(pep8);
      assert.ok(pep8.range.start.line >= lastLine, `E9989 should be on the appended line, got ${pep8.range.start.line}`);
    } finally {
      const restore = new vscode.WorkspaceEdit();
      const fullRange = new vscode.Range(new vscode.Position(0, 0), document.lineAt(document.lineCount - 1).range.end);
      restore.replace(uri, fullRange, originalText);
      await vscode.workspace.applyEdit(restore);
      await document.save();
      await config.update('runOnSave', previousRunOnSave, vscode.ConfigurationTarget.Global);
    }
  });
});
