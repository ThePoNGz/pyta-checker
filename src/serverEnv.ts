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
  return {
    ...base,
    PYTHONPATH: base.PYTHONPATH ? `${libs}${path.delimiter}${base.PYTHONPATH}` : libs,
    PYTHONIOENCODING: 'utf-8',
    PYTHONUTF8: '1',
    PYTHONUNBUFFERED: '1',
    PYTA_LSP_LIBS: libs,
    PYTA_LSP_IMPORT_STRATEGY: importStrategy,
  };
}
