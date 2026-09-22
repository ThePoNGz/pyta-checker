import * as path from 'node:path';
import { describe, expect, it } from 'vitest';
import { bundledLibsDir, serverEnv } from '../../src/serverEnv';

const EXT = path.join('C:', 'ext');

describe('serverEnv', () => {
  it('prepends bundled libs to PYTHONPATH and forces UTF-8', () => {
    const env = serverEnv(EXT, 'useBundled', { PATH: 'x', PYTHONPATH: 'existing' });
    const libs = bundledLibsDir(EXT);
    expect(env.PYTHONPATH).toBe(`${libs}${path.delimiter}existing`);
    expect(env.PYTHONIOENCODING).toBe('utf-8');
    expect(env.PYTHONUTF8).toBe('1');
    expect(env.PYTHONUNBUFFERED).toBe('1');
    expect(env.PYTA_LSP_LIBS).toBe(libs);
    expect(env.PYTA_LSP_IMPORT_STRATEGY).toBe('useBundled');
    expect(env.PATH).toBe('x');
  });
  it('sets PYTHONPATH to libs alone when none existed', () => {
    const env = serverEnv(EXT, 'fromEnvironment', {});
    expect(env.PYTHONPATH).toBe(bundledLibsDir(EXT));
    expect(env.PYTA_LSP_IMPORT_STRATEGY).toBe('fromEnvironment');
  });
});
