// Builds the environment the language server subprocess runs in.
import * as path from 'node:path';

export type ImportStrategy = 'useBundled' | 'fromEnvironment';

export function bundledLibsDir(extensionPath: string): string {
  return path.join(extensionPath, 'bundled', 'libs');
}

export function serverEnv(
  extensionPath: string,
  importStrategy: ImportStrategy,
  base: NodeJS.ProcessEnv = process.env,
): NodeJS.ProcessEnv {
  const libs = bundledLibsDir(extensionPath);
  const env: NodeJS.ProcessEnv = {
    ...base,
    PYTHONPATH: base.PYTHONPATH ? `${libs}${path.delimiter}${base.PYTHONPATH}` : libs,
    PYTHONIOENCODING: 'utf-8',
    PYTHONUTF8: '1',
    PYTHONUNBUFFERED: '1',
    PYTA_LSP_LIBS: libs,
    PYTA_LSP_IMPORT_STRATEGY: importStrategy,
  };
  // These come from whatever shell launched VS Code. They point at an environment that
  // is not the selected interpreter and they outrank it.
  for (const key of ['PYTHONHOME', 'VIRTUAL_ENV', 'CONDA_PREFIX', 'PYTHONSTARTUP']) {
    delete env[key];
  }
  return env;
}
