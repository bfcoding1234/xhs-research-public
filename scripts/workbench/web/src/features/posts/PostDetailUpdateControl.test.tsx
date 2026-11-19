import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App } from 'antd';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiService } from '@/services/api';
import PostDetailUpdateControl from './PostDetailUpdateControl';

vi.mock('@/services/api', () => ({
  apiService: {
    startPostDetailUpdate: vi.fn(),
  },
}));

const posts = [
  { id: 1, detail_level: 'card' },
  { id: 2, detail_level: 'detail', last_detail_fetched_at: '2099-01-01T00:00:00+00:00' },
];

function renderControl(selectedIds: number[] = []) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onSelectionChange = vi.fn();
  const onCreated = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <App>
        <PostDetailUpdateControl
          posts={posts}
          selectedIds={selectedIds}
          scope="global"
          onSelectionChange={onSelectionChange}
          onCreated={onCreated}
        />
      </App>
    </QueryClientProvider>,
  );
  return { onSelectionChange, onCreated };
}

describe('PostDetailUpdateControl', () => {
  beforeEach(() => {
    vi.mocked(apiService.startPostDetailUpdate).mockReset();
    vi.mocked(apiService.startPostDetailUpdate).mockResolvedValue({
      id: 'task-post-detail',
      status: 'queued',
      url: 'http://localhost/#/tasks/task-post-detail',
    });
  });

  it('creates one task for explicitly selected posts', async () => {
    const { onSelectionChange, onCreated } = renderControl([1, 2]);

    fireEvent.click(screen.getByRole('button', { name: '更新帖子详情' }));
    fireEvent.click(await screen.findByText('获取选中帖子的详情（2 篇）'));
    expect(await screen.findByText('已选择 2 篇帖子')).toBeInTheDocument();
    expect(screen.getByText(/仅预览信息 1 篇，已有详细信息 1 篇/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '创建更新任务' }));

    await waitFor(() => expect(apiService.startPostDetailUpdate).toHaveBeenCalled());
    expect(vi.mocked(apiService.startPostDetailUpdate).mock.calls[0]?.[0]).toEqual(
      expect.objectContaining({ mode: 'selected', scope: 'global', post_ids: [1, 2] }),
    );
    await waitFor(() => expect(onSelectionChange).toHaveBeenCalledWith([]));
    expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ id: 'task-post-detail' }));
  });

  it('opens a batch update without requiring a selection', async () => {
    renderControl();

    fireEvent.click(screen.getByRole('button', { name: '更新帖子详情' }));
    fireEvent.click(await screen.findByText('批量更新当前范围'));
    expect(await screen.findByText('批量更新帖子详情')).toBeInTheDocument();
    expect(screen.getByText(/需要补全或详情已过期的帖子（当前约 1 篇）/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '创建批量更新任务' }));

    await waitFor(() => expect(apiService.startPostDetailUpdate).toHaveBeenCalled());
    expect(vi.mocked(apiService.startPostDetailUpdate).mock.calls[0]?.[0]).toEqual(
      expect.objectContaining({
        mode: 'batch',
        scope: 'global',
        target: 'needs_update',
        max_posts: 300,
        post_delay_min_seconds: 1,
        post_delay_max_seconds: 3,
        batch_delay_min_seconds: 2,
        batch_delay_max_seconds: 5,
      }),
    );
  });
});
