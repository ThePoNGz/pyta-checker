import { describe, expect, it } from 'vitest';
import { formatVersion, isSupported, parsePythonVersion } from '../../src/pythonVersion';

describe('parsePythonVersion', () => {
  it('parses major.minor from probe output', () => {
    expect(parsePythonVersion('3.13\r\n')).toEqual({ major: 3, minor: 13 });
  });
  it('returns undefined for garbage', () => {
    expect(parsePythonVersion('')).toBeUndefined();
    expect(parsePythonVersion('Python was not found; run without arguments')).toBeUndefined();
  });
});

describe('isSupported', () => {
  it('accepts 3.10 and above', () => {
    expect(isSupported({ major: 3, minor: 10 })).toBe(true);
    expect(isSupported({ major: 3, minor: 14 })).toBe(true);
    expect(isSupported({ major: 4, minor: 0 })).toBe(true);
  });
  it('rejects older and undefined', () => {
    expect(isSupported({ major: 3, minor: 9 })).toBe(false);
    expect(isSupported({ major: 2, minor: 7 })).toBe(false);
    expect(isSupported(undefined)).toBe(false);
  });
});

describe('formatVersion', () => {
  it('formats as major.minor', () => {
    expect(formatVersion({ major: 3, minor: 12 })).toBe('3.12');
  });
});
