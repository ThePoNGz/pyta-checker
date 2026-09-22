import * as vscode from 'vscode';
import { TARGETS, planDisable, planEnable, type Snapshot, type Write } from './onlyPytaLogic';
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

export async function applyOnlyPyta(
  enabled: boolean,
  context: vscode.ExtensionContext,
  log: vscode.LogOutputChannel,
): Promise<void> {
  const saved = context.globalState.get<Snapshot>(SAVED_KEY);
  let writes: Write[];
  if (enabled) {
    const current: Snapshot = {};
    for (const target of TARGETS) {
      const inspected = vscode.workspace.getConfiguration(target.section).inspect<unknown>(target.key);
      current[target.section] = inspected?.globalValue === undefined ? null : inspected.globalValue;
    }
    const plan = planEnable(current, saved);
    await context.globalState.update(SAVED_KEY, plan.saved);
    writes = plan.writes;
  } else {
    writes = planDisable(saved);
    await context.globalState.update(SAVED_KEY, undefined);
  }
  for (const write of writes) {
    try {
      await vscode.workspace.getConfiguration(write.section).update(write.key, write.value, vscode.ConfigurationTarget.Global);
      log.info(`${enabled ? 'Set' : 'Restored'} ${write.section}.${write.key}`);
    } catch (error) {
      log.info(`Skipping ${write.section}.${write.key} (extension not installed?): ${String(error)}`);
    }
  }
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
  await config.update(SETTING, !current, vscode.ConfigurationTarget.Global);
  void vscode.window.showInformationMessage(
    current ? 'PythonTA: other Python problems are visible again.' : 'PythonTA: showing only PythonTA problems.',
  );
}
