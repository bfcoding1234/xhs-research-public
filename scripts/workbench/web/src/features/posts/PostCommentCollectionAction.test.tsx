import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { App } from 'antd';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import PostCommentCollectionAction, {
  PostCommentQuickCollectionAction,
} from './PostCommentCollectionAction';

const { startPostCommentCollection } = vi.hoisted(() => ({
  startPostCommentCollection: vi.fn(),
}));

vi.mock('@/services/api', () => ({
  apiService: { startPostCommentCollection },
}));
vi.mock('@umijs/max', () => ({
  history: { push: vi.fn() },
}));

describe('PostCommentCollectionAction', () => {
  beforeEach(() => {
    startPostCommentCollection.mockReset();
    startPostCommentCollection.mockResolvedValue({
      id: 'task-comments-1',
      status: 'queued',
      url: '/tasks/task-comments-1',
    });
  });

  it('uses continuation with the one-to-two-second defaults and allows up to twenty pages', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <App>
          <PostCommentCollectionAction
            post={{ id: 7, note_id: 'note-7', title: '示例帖子', comments_count: 88 }}
          />
        </App>
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: /补充评论/ }));
    expect(screen.getByText('从上次位置继续补充')).toBeInTheDocument();
    expect(screen.getByRole('spinbutton', { name: '随机等待最短' })).toHaveValue('1');
    expect(screen.getByRole('spinbutton', { name: '随机等待最长' })).toHaveValue('2');
    fireEvent.change(screen.getByRole('spinbutton', { name: '抓取页数' }), {
      target: { value: '20' },
    });
    fireEvent.click(screen.getByRole('button', { name: '开始采集' }));

    await waitFor(() =>
      expect(startPostCommentCollection).toHaveBeenCalledWith(7, {
        collection_mode: 'continue',
        requested_pages: 20,
        page_delay_min_seconds: 1,
        page_delay_max_seconds: 2,
        include_sub_comments: false,
        sub_comment_page_limit: 20,
      }),
    );
    expect(await screen.findByText('创建成功，任务已进入队列')).toBeInTheDocument();
  });

  it('uses refresh when continuation is exhausted and exposes the sub-comment budget', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <App>
          <PostCommentCollectionAction
            post={{ id: 8, note_id: 'note-8', title: '已到末页' }}
            checkpoint={{
              status: 'exhausted',
              completed_pages: 6,
              last_task_id: 'task-old',
              last_error: '',
              captured_at: '2026-08-11T10:00:00Z',
              updated_at: '2026-08-11T10:00:00Z',
            }}
          />
        </App>
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: /补充评论/ }));
    expect(screen.getByRole('radio', { name: '继续补充' })).toBeDisabled();
    expect(screen.getByRole('radio', { name: '重新更新' })).toBeChecked();
    fireEvent.click(screen.getByRole('switch', { name: '抓取楼中楼' }));
    fireEvent.change(await screen.findByRole('spinbutton', { name: '楼中楼请求预算' }), {
      target: { value: '30' },
    });
    fireEvent.click(screen.getByRole('button', { name: '开始采集' }));

    await waitFor(() =>
      expect(startPostCommentCollection).toHaveBeenCalledWith(8, {
        collection_mode: 'refresh',
        requested_pages: 1,
        page_delay_min_seconds: 1,
        page_delay_max_seconds: 2,
        include_sub_comments: true,
        sub_comment_page_limit: 30,
      }),
    );
  });

  it('starts a silent quick collection with the same default form values', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <App>
          <PostCommentQuickCollectionAction
            post={{ id: 9, note_id: 'note-9', title: '快捷补充帖子' }}
          />
        </App>
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: '快捷补充评论' }));

    await waitFor(() =>
      expect(startPostCommentCollection).toHaveBeenCalledWith(9, {
        collection_mode: 'continue',
        requested_pages: 1,
        page_delay_min_seconds: 1,
        page_delay_max_seconds: 2,
        include_sub_comments: false,
        sub_comment_page_limit: 20,
      }),
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.queryByText('创建成功，任务已进入队列')).not.toBeInTheDocument();
  });
});
