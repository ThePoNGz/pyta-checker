// Interpreter discovery. Asks the setting, then the Python extension, then PATH, and
// says something when the interpreter the user picked could not be used.
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

/**
 * Find the first interpreter that runs and is new enough.
 *
 * @param settingPath pythonta.interpreter, empty string when the user set nothing
 * @param log the PythonTA output channel
 * @returns the chosen interpreter, or an error string listing what was tried
 */
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
  let configured: string | undefined;
  const result = await selectPython(candidates, defaultProbe, (candidate, reason) => {
    if (candidate.origin === 'setting' && configured === undefined) {
      configured = reason;
    }
  });
  if ('error' in result) {
    log.error(result.error);
  } else {
    log.info(`Using Python ${formatVersion(result.version)} at ${result.path} (${result.origin})`);
    if (configured !== undefined) {
      reportFallback(settingPath, configured, result.path, log);
    }
  }
  return result;
}

let warnedFallback = false;

/** Falling back silently leaves the student with results from an interpreter they did not pick. */
function reportFallback(configuredPath: string, reason: string, used: string, log: vscode.LogOutputChannel): void {
  const message = `PythonTA: the interpreter set in pythonta.interpreter (${configuredPath}) could not be used (${reason}). Using ${used} instead.`;
  log.warn(message);
  // Every restart runs discovery again, so this is worth saying once a session.
  if (warnedFallback) {
    return;
  }
  warnedFallback = true;
  void vscode.window.showWarningMessage(message, 'Show Output').then((choice) => {
    if (choice) {
      void vscode.commands.executeCommand('pythonta.showOutput');
    }
  });
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
