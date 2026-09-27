import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, rmSync, rmdirSync, writeFileSync } from 'node:fs';
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
      // The .bin entry is a .cmd shim on Windows, which execFileSync cannot start
      // without a shell, so the CLI script is run with this node directly.
      const vsce = join(root, 'node_modules', '@vscode', 'vsce', 'vsce');
      const listing = execFileSync(process.execPath, [vsce, 'ls', '--no-dependencies'], {
        cwd: root,
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'ignore'],
      });
      expect(listing).not.toContain('pyta-lsp-server-0.0.0-vsixtest.tar.gz');
    } finally {
      rmSync(marker, { force: true });
      if (!hadDist) {
        // Only the empty folder this test made. A build that landed meanwhile stays.
        try {
          rmdirSync(dist);
        } catch {
          // not empty any more, or already gone
        }
      }
    }
  }, 60_000);
});
