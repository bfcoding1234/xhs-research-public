import { describe, expect, it } from 'vitest';
import { defaultDeepFitsDiscovery } from './settings';

describe('default research settings validation', () => {
  it('accepts a deep default equal to the discovery default', () => {
    expect(defaultDeepFitsDiscovery(20, 20)).toBe(true);
  });

  it('rejects a deep default above the discovery default', () => {
    expect(defaultDeepFitsDiscovery(21, 20)).toBe(false);
  });
});
