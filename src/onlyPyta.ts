import * as vscode from 'vscode';
import {
  TARGETS,
  isIgnoreAll,
  isUnregisteredSettingError,
  newlyClaimed,
  planDisable,
  planEnable,
  type Snapshot,
  type Target,
  type Write,
} from './onlyPytaLogic';
import { SECTION } from './settings';

export const SAVED_KEY = 'pythonta.savedIgnore';
export const PROMPTED_KEY = 'pythonta.promptedOnlyPyta';
const SETTING = 'hideOtherPythonDiagnostics';
const SHOW_OUTPUT = 'Show Output';

export interface ApplyOutcome {
  /** Writes that changed something; nothing else is worth a language-server restart. */
  landed: number;
  /** Writes refused for a reason other than the target extension being absent. */
  failed: number;
  /** Targets a workspace value outranks, where the global write changes nothing. */
  blocked: string[];
}

export interface ApplyOptions {
  /** Activation and the toggle report for themselves. */
  silent?: boolean;
}

function isHideEnabled(): boolean {
  return vscode.workspace.getConfiguration(SECTION).get<boolean>(SETTING, false);
}

export async function maybePromptFirstRun(context: vscode.ExtensionContext): Promise<void> {
  if (context.globalState.get<boolean>(PROMPTED_KEY) || process.env.PYTA_SKIP_PROMPT) {
    return;
  }
  await context.globalState.update(PROMPTED_KEY, true);
  // Settings Sync carries the setting between machines but not globalState, so on a
  // second machine it can already be on with nothing recorded here.
  if (isHideEnabled()) {
    return;
  }
  const choice = await vscode.window.showInformationMessage(
    "PythonTA Checker: hide Pylance and basedpyright problems so only PythonTA's show? Autocomplete keeps working. Change it later with 'PythonTA: Toggle Only-PythonTA Problems'.",
    'Yes',
    'No',
  );
  if (choice !== 'Yes' && choice !== 'No') {
    return;
  }
  // The prompt can sit open while the toggle changes the same setting, so the answer
  // is compared against the value now rather than the one read above.
  const wanted = choice === 'Yes';
  if (isHideEnabled() === wanted) {
    return;
  }
  await vscode.workspace.getConfiguration(SECTION).update(SETTING, wanted, vscode.ConfigurationTarget.Global);
}

let applying: Promise<unknown> = Promise.resolve();
let lastRequested: boolean | undefined;
let warnedScoped = false;

export function applyOnlyPyta(
  enabled: boolean,
  context: vscode.ExtensionContext,
  log: vscode.LogOutputChannel,
  options: ApplyOptions = {},
): Promise<ApplyOutcome> {
  lastRequested = enabled;
  const next = applying.then(() => applyOnlyPytaNow(enabled, context, log, options));
  applying = next.catch(() => undefined);
  return next;
}

/** The configuration listener also fires for the toggle's own write, which has already been applied. */
export function syncOnlyPyta(
  enabled: boolean,
  context: vscode.ExtensionContext,
  log: vscode.LogOutputChannel,
): Promise<ApplyOutcome | undefined> {
  if (enabled === lastRequested) {
    return Promise.resolve(undefined);
  }
  return applyOnlyPyta(enabled, context, log);
}

async function applyOnlyPytaNow(
  enabled: boolean,
  context: vscode.ExtensionContext,
  log: vscode.LogOutputChannel,
  options: ApplyOptions,
): Promise<ApplyOutcome> {
  const saved = context.globalState.get<Snapshot>(SAVED_KEY);
  const current = readCurrent();
  let writes: Write[];
  let owed: Snapshot;
  let claiming: Set<string>;
  // A cycle that overwrites nothing owes nothing, so it must leave the snapshot to
  // whichever window or machine did the writing. Recording "absent" here instead is
  // what makes a later disable delete the user's value rather than restore it.
  let records = true;
  if (enabled) {
    const plan = planEnable(current, saved);
    writes = plan.writes;
    records = writes.length > 0;
    // Written before the overwrites so a crash mid-loop cannot lose the originals;
    // reconciled against what actually landed once the loop is done.
    if (records) {
      await context.globalState.update(SAVED_KEY, plan.saved);
    }
    owed = records ? { ...plan.saved } : {};
    claiming = records ? newlyClaimed(saved, plan.saved) : new Set();
  } else {
    writes = planDisable(saved, current);
    // Anything the snapshot claims but planDisable declined is the user's again.
    owed = Object.fromEntries(writes.map((w) => [w.section, saved?.[w.section]]));
    claiming = new Set();
  }
  let landed = 0;
  let failed = 0;
  for (const write of writes) {
    try {
      await vscode.workspace.getConfiguration(write.section).update(write.key, write.value, vscode.ConfigurationTarget.Global);
      landed += 1;
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
        failed += 1;
        log.warn(`Could not write ${write.section}.${write.key}: ${String(error)}`);
      }
    }
  }
  // The snapshot is the only record of the user's original values: it holds exactly
  // the settings we have overwritten and still owe back. A failure here can only
  // leave it over-claiming, which planDisable filters out, so it is not fatal.
  if (records) {
    try {
      await context.globalState.update(SAVED_KEY, Object.keys(owed).length > 0 ? owed : undefined);
    } catch (error) {
      log.warn(`Could not update the saved ignore snapshot: ${String(error)}`);
    }
  }
  // A workspace value outranks the user setting whichever way the toggle went.
  const blocked = scopedOverrides(enabled);
  if (blocked.length > 0) {
    log.warn(`Only-PythonTA cannot ${enabled ? 'hide' : 'restore'} ${join(blocked)}: a workspace setting outranks the user setting.`);
    // Activation re-applies on every window open, so an unconditional toast here
    // reappears forever with nothing new to report.
    if (!options.silent && !warnedScoped) {
      warnedScoped = true;
      void vscode.window.showWarningMessage(scopedOverrideMessage(blocked, enabled));
    }
  }
  // Restarting the other language servers throws away their analysis, so it is worth
  // doing only when a setting actually changed.
  if (landed > 0) {
    await restartOtherServers(log);
  }
  return { landed, failed, blocked };
}

/**
 * Global writes lose to a workspace or folder value, so the toggle can silently do
 * nothing - but only when the winning value leaves the problems on the wrong side of
 * what we just asked for. Our sentinel hides everything, so a copy of it in a higher
 * scope carries an enable and blocks a disable; any other value is the mirror image.
 */
function scopedOverrides(enabled: boolean): string[] {
  return TARGETS.filter((target) =>
    higherScopeValues(target).some((value) => (enabled ? !isIgnoreAll(value) : isIgnoreAll(value))),
  ).map((target) => `${target.section}.${target.key}`);
}

/** A folder's .vscode/settings.json is invisible to an inspect with no resource. */
function higherScopeValues(target: Target): unknown[] {
  const found: unknown[] = [];
  const collect = (resource?: vscode.Uri): void => {
    const inspected = vscode.workspace.getConfiguration(target.section, resource).inspect<unknown>(target.key);
    for (const value of [inspected?.workspaceValue, inspected?.workspaceFolderValue]) {
      if (value !== undefined) {
        found.push(value);
      }
    }
  };
  collect();
  for (const folder of vscode.workspace.workspaceFolders ?? []) {
    collect(folder.uri);
  }
  return found;
}

function join(names: string[]): string {
  return names.join(' and ');
}

function scopedOverrideMessage(blocked: string[], enabled: boolean): string {
  const many = blocked.length > 1;
  const state = enabled ? 'visible' : 'hidden';
  return `PythonTA: ${join(blocked)} ${many ? 'are' : 'is'} set for this workspace, so those problems stay ${state}. Remove ${many ? 'them' : 'it'} from the workspace settings to change that.`;
}

function readCurrent(): Snapshot {
  const current: Snapshot = {};
  for (const target of TARGETS) {
    const inspected = vscode.workspace.getConfiguration(target.section).inspect<unknown>(target.key);
    current[target.section] = inspected?.globalValue === undefined ? null : inspected.globalValue;
  }
  return current;
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

export async function toggleOnlyPyta(
  context: vscode.ExtensionContext,
  log: vscode.LogOutputChannel,
): Promise<void> {
  const config = vscode.workspace.getConfiguration(SECTION);
  const enabled = !config.get<boolean>(SETTING, false);
  // The configuration event can arrive while the write below is still in flight, so
  // this value is claimed before it: the listener then has nothing left to apply.
  const previous = lastRequested;
  lastRequested = enabled;
  try {
    await config.update(SETTING, enabled, vscode.ConfigurationTarget.Global);
  } catch {
    lastRequested = previous;
    void vscode.window.showErrorMessage('PythonTA: could not change the setting.');
    return;
  }
  // The writes that do the work happen here rather than through the configuration
  // listener, so the toggle reports what actually landed.
  let outcome: ApplyOutcome;
  try {
    outcome = await applyOnlyPyta(enabled, context, log, { silent: true });
  } catch (error) {
    log.error(`Only-PythonTA update failed: ${String(error)}`);
    await showApplyFailure();
    return;
  }
  if (outcome.failed > 0) {
    await showApplyFailure();
    return;
  }
  if (outcome.blocked.length > 0) {
    void vscode.window.showWarningMessage(scopedOverrideMessage(outcome.blocked, enabled));
    return;
  }
  void vscode.window.showInformationMessage(
    enabled ? 'PythonTA: showing only PythonTA problems.' : 'PythonTA: other Python problems are visible again.',
  );
}

async function showApplyFailure(): Promise<void> {
  const choice = await vscode.window.showErrorMessage(
    "PythonTA: could not update all of the other extensions' settings. The log says which.",
    SHOW_OUTPUT,
  );
  if (choice) {
    await vscode.commands.executeCommand('pythonta.showOutput');
  }
}
