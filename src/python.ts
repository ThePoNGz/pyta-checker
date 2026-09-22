import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { PythonExtension } from '@vscode/python-extension';
import * as vscode from 'vscode';
import { formatVersion } from './pythonVersion';
import { pathCandidates, selectPython, type Candidate, type Probe, type PythonInfo } from './pythonSelect';

const execFileAsync = promisify(execFile);

const defaultProbe: Probe = async (command, args) => {
  const { stdout } = await execFileAsync(command, args, { timeout: 15_000, windowsHide: true });
  return stdout;
};

async function pythonExtensionCandidate(log: vscode.LogOutputChannel): Promise<Candidate | undefined> {
  try {
    const api = await PythonExtension.api();
    const active = api.environments.getActiveEnvironmentPath();
    const resolved = await api.environments.resolveEnvironment(active);
    const executable = resolved?.executable.uri?.fsPath;
    if (executable) {
      return { path: executable, origin: 'python-extension' };
    }
    log.warn(`Python extension has no runnable interpreter for ${active.path}`);
  } catch (error) {
    log.warn(`Python extension API unavailable: ${String(error)}`);
  }
  return undefined;
}

export async function findPython(settingPath: string, log: vscode.LogOutputChannel): Promise<PythonInfo | { error: string }> {
  const candidates: Candidate[] = [];
  if (settingPath) {
    candidates.push({ path: settingPath, origin: 'setting' });
  }
  const fromExtension = await pythonExtensionCandidate(log);
  if (fromExtension) {
    candidates.push(fromExtension);
  }
  candidates.push(...pathCandidates(process.platform));
  const result = await selectPython(candidates, defaultProbe);
  if ('error' in result) {
    log.error(result.error);
  } else {
    log.info(`Using Python ${formatVersion(result.version)} at ${result.path} (${result.origin})`);
  }
  return result;
}

export async function onInterpreterChanged(
  listener: () => void,
  log: vscode.LogOutputChannel,
): Promise<vscode.Disposable | undefined> {
  try {
    const api = await PythonExtension.api();
    return api.environments.onDidChangeActiveEnvironmentPath(() => listener());
  } catch (error) {
    log.warn(`Cannot watch interpreter changes: ${String(error)}`);
    return undefined;
  }
}
