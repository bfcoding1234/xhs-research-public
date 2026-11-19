import { describe, expect, it } from 'vitest';
import {
  activeTaskIds,
  didActiveTaskSettle,
  didTaskSettle,
} from './taskPolling';

describe('task polling transitions', () => {
  it('runs a final project sync when any previously active task becomes terminal', () => {
    const previous = activeTaskIds([
      { id: 'research', status: 'running' },
      { id: 'report', status: 'queued' },
    ]);
    const current = activeTaskIds([
      { id: 'research', status: 'completed' },
      { id: 'report', status: 'running' },
    ]);

    expect(didActiveTaskSettle(previous, current)).toBe(true);
  });

  it('does not finalize on initial terminal data or repeated terminal refetches', () => {
    const terminal = activeTaskIds([{ id: 'research', status: 'completed' }]);

    expect(didActiveTaskSettle(undefined, terminal)).toBe(false);
    expect(didActiveTaskSettle(terminal, terminal)).toBe(false);
  });

  it('runs one final task-detail sync only for active-to-terminal transitions', () => {
    expect(didTaskSettle('running', 'completed')).toBe(true);
    expect(didTaskSettle('waiting_login', 'failed')).toBe(true);
    expect(didTaskSettle(undefined, 'completed')).toBe(false);
    expect(didTaskSettle('completed', 'completed')).toBe(false);
    expect(didTaskSettle('running', 'waiting_login')).toBe(false);
  });
});
