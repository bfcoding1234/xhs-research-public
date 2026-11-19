import { describe, expect, it } from 'vitest';
import { isLoopbackHost } from './network';

describe('loopback host detection', () => {
  it.each(['127.0.0.1', '127.8.9.10', 'localhost', 'LOCALHOST.', '::1', '[::1]'])(
    'recognizes %s as loopback',
    (host) => expect(isLoopbackHost(host)).toBe(true),
  );

  it.each(['0.0.0.0', '::', '192.168.1.20', 'workbench.local', ''])('flags %s as non-loopback', (host) => {
    expect(isLoopbackHost(host)).toBe(false);
  });
});
