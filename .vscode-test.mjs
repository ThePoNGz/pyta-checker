import { defineConfig } from '@vscode/test-cli';
import path from 'node:path';

export default defineConfig({
  label: 'integration',
  files: 'out/test/integration/**/*.test.js',
  version: 'stable',
  workspaceFolder: path.resolve('test/fixtures'),
  launchArgs: ['--disable-gpu'],
  env: { PYTA_SKIP_PROMPT: '1' },
  mocha: { ui: 'tdd', timeout: 180_000, color: true },
});
