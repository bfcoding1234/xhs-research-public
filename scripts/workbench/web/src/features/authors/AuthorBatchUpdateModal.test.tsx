import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { App } from 'antd';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiService } from '@/services/api';
import type { AppSettings } from '@/types';
import AuthorBatchUpdateModal from './AuthorBatchUpdateModal';

const authors = [
  { id: 1, author_id: 'author-a', display_name: '作者甲' },
  { id: 2, author_id: 'author-b', display_name: '作者乙' },
];

function renderModal(
  mode: 'basic_info' | 'posts',
  onComplete = vi.fn(),
  onClose = vi.fn(),
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <App>
        <AuthorBatchUpdateModal
          open
          mode={mode}
          authors={authors}
          onClose={onClose}
          onComplete={onComplete}
        />
      </App>
    </QueryClientProvider>,
  );
  return { onComplete, onClose };
}

describe('AuthorBatchUpdateModal', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('creates one independent basic-info task per author', async () => {
    const createTask = vi.spyOn(apiService, 'createTask');
    createTask
      .mockResolvedValueOnce({ id: 'task-1', status: 'queued', url: '/tasks/task-1' })
      .mockResolvedValueOnce({ id: 'task-2', status: 'queued', url: '/tasks/task-2' });
    const { onComplete, onClose } = renderModal('basic_info');

    fireEvent.click(screen.getByRole('button', { name: '创建 2 个更新任务' }));

    await waitFor(() => expect(onComplete).toHaveBeenCalledOnce());
    expect(createTask).toHaveBeenCalledTimes(2);
    expect(createTask.mock.calls.map((call) => call[2].source.author_ids)).toEqual([
      ['author-a'],
      ['author-b'],
    ]);
    expect(createTask.mock.calls.map((call) => call[2].author_update?.scopes)).toEqual([
      ['basic_info'],
      ['basic_info'],
    ]);
    expect(onComplete.mock.calls[0]?.[0].successes).toHaveLength(2);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('uses the same per-author post defaults for every selected author', async () => {
    vi.spyOn(apiService, 'settings').mockResolvedValue({
      default_discovery: 12,
      default_deep: 3,
      max_author_notes: 50,
    } as AppSettings);
    const createTask = vi.spyOn(apiService, 'createTask');
    createTask
      .mockResolvedValueOnce({ id: 'task-1', status: 'queued', url: '/tasks/task-1' })
      .mockResolvedValueOnce({ id: 'task-2', status: 'queued', url: '/tasks/task-2' });
    const { onComplete } = renderModal('posts');

    expect(await screen.findByText('每位作者最多批量更新帖子数')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '创建 2 个更新任务' }));

    await waitFor(() => expect(onComplete).toHaveBeenCalledOnce());
    expect(createTask.mock.calls.map((call) => call[2].limits)).toEqual([
      { discovery: 12, deep: 0 },
      { discovery: 12, deep: 0 },
    ]);
    expect(createTask.mock.calls.map((call) => call[2].author_update?.scopes)).toEqual([
      ['preview_posts'],
      ['preview_posts'],
    ]);
  });
});
