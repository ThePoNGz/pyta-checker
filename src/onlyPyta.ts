import * as vscode from 'vscode';
import {
  TARGETS,
  isUnregisteredSettingError,
  newlyClaimed,
  planDisable,
  planEnable,
  type Snapshot,
  type Write,
} from './onlyPytaLogic';
import { SECTION } from './settings';

export const SAVED_KEY = 'pythonta.savedIgnore';
export const PROMPTED_KEY = 'pythonta.promptedOnlyPyta';
const SETTING = 'hideOtherPythonDiagnostics';

export async function maybePromptFirstRun(context: vscode.ExtensionContext): Promise<void> {
  if (context.globalState.get<boolean>(PROMPTED_KEY) || process.env.PYTA_SKIP_PROMPT) {
    return;
  }
  await context.globalState.update(PROMPTED_KEY, true);
  const choice = await vscode.window.showInformationMessage(
    "PythonTA Checker: hide Pylance and basedpyright problems so only PythonTA's show? Autocomplete keeps working. Change it later with 'PythonTA: Toggle Only-PythonTA Problems'.",
    'Yes',
    'No',
  );
  if (choice === 'Yes') {
    await vscode.workspace.getConfiguration(SECTION).update(SETTING, true, vscode.ConfigurationTarget.Global);
  }
}

let applying: Promise<void> = Promise.resolve();

export function applyOnlyPyta(enabled: boolean, context: vscode.ExtensionContext, log: vscode.LogOutputChannel): Promise<void> {
  const next = applying.then(() => applyOnlyPytaNow(enabled, context, log));
  applying = next.catch(() => undefined);
  return next;
}

async function applyOnlyPytaNow(
  enabled: boolean,
  context: vscode.ExtensionContext,
  log: vscode.LogOutputChannel,
): Promise<void> {
  const saved = context.globalState.get<Snapshot>(SAVED_KEY);
  let writes: Write[];
  let owed: Snapshot;
  let claiming: Set<string>;
  if (enabled) {
    const current: Snapshot = {};
    for (const target of TARGETS) {
      const inspected = vscode.workspace.getConfiguration(target.section).inspect<unknown>(target.key);
      current[target.section] = inspected?.globalValue === undefined ? null : inspected.globalValue;
    }
    const plan = planEnable(current, saved);
    // Written before the overwrites so a crash mid-loop cannot lose the originals;
    // reconciled against what actually landed once the loop is done.
    await context.globalState.update(SAVED_KEY, plan.saved);
    owed = { ...plan.saved };
    claiming = newlyClaimed(saved, plan.saved);
    writes = plan.writes;
  } else {
    owed = { ...saved };
    claiming = new Set();
    writes = planDisable(saved);
  }
  for (const write of writes) {
    try {
      await vscode.workspace.getConfiguration(write.section).update(write.key, write.value, vscode.ConfigurationTarget.Global);
      if (!enabled) {
        delete owed[write.section];
      }
      log.info(`${enabled ? 'Set' : 'Restored'} ${write.section}.${write.key}`);
    } catch (error) {
      // A refused write changes nothing, so it neither claims a setting on enable
      // nor discharges what we owe on disable. The reason only picks the log line.
      if (claiming.has(write.section)) {
        delete owed[write.section];
      }
      if (isUnregisteredSettingError(error)) {
        log.info(`Skipping ${write.section}.${write.key} (extension not installed)`);
      } else {
        log.warn(`Could not write ${write.section}.${write.key}: ${String(error)}`);
      }
    }
  }
  // The snapshot is the only record of the user's original values: it holds exactly
  // the settings we have overwritten and still owe back.
  await context.globalState.update(SAVED_KEY, Object.keys(owed).length > 0 ? owed : undefined);
  await restartOtherServers(log);
}

async function restartOtherServers(log: vscode.LogOutputChannel): Promise<void> {
  const ids = new Set(await vscode.commands.getCommands(true));
  for (const target of TARGETS) {
    if (!ids.has(target.restartCommand)) {
      continue;
    }
    try {
      await vscode.commands.executeCommand(target.restartCommand);
    } catch (error) {
      log.warn(`Could not run ${target.restartCommand}: ${String(error)}`);
    }
  }
}

export async function toggleOnlyPyta(): Promise<void> {
  const config = vscode.workspace.getConfiguration(SECTION);
  const current = config.get<boolean>(SETTING, false);
  try {
    await config.update(SETTING, !current, vscode.ConfigurationTarget.Global);
  } catch {
    void vscode.window.showErrorMessage('PythonTA: could not change the setting.');
    return;
  }
  void vscode.window.showInformationMessage(
    current ? 'PythonTA: other Python problems are visible again.' : 'PythonTA: showing only PythonTA problems.',
  );
}
