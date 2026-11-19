import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { TaskReceipt } from '@/types';
import TaskCreatedModal from './TaskCreatedModal';

const task: TaskReceipt = {
  id: 'task-created',
  status: 'queued',
  url: '/#/tasks/task-created',
};

describe('TaskCreatedModal', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('stays on the current page automatically after five seconds', () => {
    vi.useFakeTimers();
    const onStay = vi.fn();
    const onView = vi.fn();
    render(<TaskCreatedModal task={task} onStay={onStay} onView={onView} />);

    expect(screen.getByRole('button', { name: '留在当前页（5 秒后自动）' })).toHaveClass(
      'ant-btn-primary',
    );
    act(() => vi.advanceTimersByTime(5_000));
    expect(onStay).toHaveBeenCalledWith(task);
    expect(onView).not.toHaveBeenCalled();
  });

  it('opens task details only when the user explicitly chooses it', () => {
    const onStay = vi.fn();
    const onView = vi.fn();
    render(<TaskCreatedModal task={task} onStay={onStay} onView={onView} />);

    fireEvent.click(screen.getByRole('button', { name: '查看任务详情' }));
    expect(onView).toHaveBeenCalledWith(task);
    expect(onStay).not.toHaveBeenCalled();
  });
});
