import * as vscode from 'vscode';
import type { ImportStrategy } from './serverEnv';

export const SECTION = 'pythonta';

export interface PytaSettings {
  runOnSave: boolean;
  runOnOpen: boolean;
  configPath: string;
  importStrategy: ImportStrategy;
  interpreter: string;
  hideOtherPythonDiagnostics: boolean;
}

export function getSettings(): PytaSettings {
  const config = vscode.workspace.getConfiguration(SECTION);
  const strategy = config.get<string>('importStrategy', 'useBundled');
  return {
    runOnSave: config.get<boolean>('runOnSave', true),
    runOnOpen: config.get<boolean>('runOnOpen', true),
    configPath: config.get<string>('configPath', ''),
    importStrategy: strategy === 'fromEnvironment' ? 'fromEnvironment' : 'useBundled',
    interpreter: config.get<string>('interpreter', ''),
    hideOtherPythonDiagnostics: config.get<boolean>('hideOtherPythonDiagnostics', false),
  };
}

export function serverSettings(s: PytaSettings): { runOnSave: boolean; runOnOpen: boolean; configPath: string } {
  return { runOnSave: s.runOnSave, runOnOpen: s.runOnOpen, configPath: s.configPath };
}
