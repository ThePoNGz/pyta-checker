// Sets up the language client that talks to the pyta_lsp server, and the check request.
import * as vscode from 'vscode';
import {
  ExecuteCommandRequest,
  LanguageClient,
  TransportKind,
  type LanguageClientOptions,
  type ServerOptions,
} from 'vscode-languageclient/node';
import { serverEnv } from './serverEnv';
import { SECTION, getSettings, serverSettings } from './settings';

export const STATUS_NOTIFICATION = 'pyta/status';
export const CHECK_COMMAND = 'pyta.check';

export interface StatusParams {
  uri: string;
  state: 'checking' | 'done';
  count: number | null;
}

export function createClient(pythonPath: string, extensionPath: string, log: vscode.LogOutputChannel): LanguageClient {
  const settings = getSettings();
  const serverOptions: ServerOptions = {
    command: pythonPath,
    args: ['-m', 'pyta_lsp'],
    transport: TransportKind.stdio,
    options: { cwd: extensionPath, env: serverEnv(extensionPath, settings.importStrategy) },
  };
  const clientOptions: LanguageClientOptions = {
    documentSelector: [{ scheme: 'file', language: 'python' }],
    outputChannel: log,
    diagnosticCollectionName: 'PythonTA',
    initializationOptions: () => serverSettings(getSettings()),
    synchronize: { configurationSection: SECTION },
  };
  return new LanguageClient(SECTION, 'PythonTA', serverOptions, clientOptions);
}

export async function requestCheck(client: LanguageClient, uri: vscode.Uri): Promise<void> {
  await client.sendRequest(ExecuteCommandRequest.type, {
    command: CHECK_COMMAND,
    arguments: [client.code2ProtocolConverter.asUri(uri)],
  });
}
