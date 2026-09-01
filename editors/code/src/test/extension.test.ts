import * as assert from 'assert';
import * as path from 'path';
import * as vscode from 'vscode';

suite('optics-framework-lsp', () => {
  test('reports a diagnostic for a step naming no module or keyword', async () => {
    const folder = vscode.workspace.workspaceFolders?.[0];
    assert.ok(folder, 'expected the broken-suite fixture to be open as the workspace');

    const uri = vscode.Uri.file(path.join(folder!.uri.fsPath, 'test_cases.csv'));
    await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(uri));

    const diagnostics = await waitForDiagnostics(uri);
    const finding = diagnostics.find((d) => d.message.includes('Missing Module'));

    assert.ok(finding, `expected a diagnostic mentioning "Missing Module", got: ${JSON.stringify(diagnostics)}`);
    assert.strictEqual(finding!.severity, vscode.DiagnosticSeverity.Error);
    assert.strictEqual(finding!.range.start.line, 2);
  });
});

async function waitForDiagnostics(uri: vscode.Uri, timeoutMs = 20_000): Promise<vscode.Diagnostic[]> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const diagnostics = vscode.languages.getDiagnostics(uri);
    if (diagnostics.length > 0) {
      return diagnostics;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  return vscode.languages.getDiagnostics(uri);
}
