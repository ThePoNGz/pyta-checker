import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

// The default lives in package.json, so the setting reads as on before any window has
// written anything. vitest runs from the repo root, so that is where we read it from.
const manifest = JSON.parse(readFileSync(join(process.cwd(), 'package.json'), 'utf8'));
const setting = manifest.contributes.configuration.properties['pythonta.hideOtherPythonDiagnostics'];

describe('the hideOtherPythonDiagnostics contribution', () => {
  it('hides the other Python problems by default', () => {
    expect(setting.default).toBe(true);
  });

  it('says it is on by default and names the command that changes it', () => {
    expect(setting.description).toContain('on by default');
    expect(setting.description).toContain('PythonTA: Toggle Only-PythonTA Problems');
  });
});
