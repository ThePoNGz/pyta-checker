import * as assert from 'node:assert';
import * as vscode from 'vscode';
import { codeOf, openFixture, pytaDiagnostics, waitForDiagnosticsChange, waitForPytaDiagnostics } from './helpers';

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
    assert.ok(diagnostics.length > 0);
  });

  test('reports a syntax error as E0001', async () => {
    const uri = await openFixture('syntax_error.py');
    const diagnostics = await waitForPytaDiagnostics(uri, (d) => d.length > 0);
    assert.deepStrictEqual(diagnostics.map(codeOf), ['E0001']);
    assert.strictEqual(diagnostics[0].range.start.line, 3);
  });

  test('the check command re-runs on the active file', async () => {
    const uri = await openFixture('no_config.py');
    await waitForPytaDiagnostics(uri, (d) => d.some((x) => codeOf(x) === 'E9999'));
    const changed = waitForDiagnosticsChange(uri);
    await vscode.commands.executeCommand('pythonta.check');
    await changed;
    const codes = pytaDiagnostics(uri).map(codeOf);
    assert.ok(codes.includes('E9999'), `expected E9999 after re-check: ${codes}`);
  });
});
