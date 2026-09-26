import { execFileSync } from 'node:child_process';
import { mkdirSync, rmSync, writeFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

// The server tarball is written to dist/ next to the bundled extension code, and vsce
// packs everything under dist/ that .vscodeignore does not exclude. Shipping the
// tarball inside the VSIX doubles its size for nothing.
describe('the VSIX contents', () => {
  it('leave the server tarball out', () => {
    const root = process.cwd();
    const dist = join(root, 'dist');
    const hadDist = existsSync(dist);
    const marker = join(dist, 'pyta-lsp-server-0.0.0-vsixtest.tar.gz');
    mkdirSync(dist, { recursive: true });
    writeFileSync(marker, '');
    try {
      const listing = execFileSync(join(root, 'node_modules', '.bin', 'vsce'), ['ls', '--no-dependencies'], {
        cwd: root,
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'ignore'],
      });
      expect(listing).not.toContain('pyta-lsp-server-0.0.0-vsixtest.tar.gz');
    } finally {
      rmSync(marker, { force: true });
      if (!hadDist) rmSync(dist, { recursive: true, force: true });
    }
  }, 60_000);
});
