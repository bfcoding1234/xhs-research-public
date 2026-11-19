import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { App } from 'antd';
import { describe, expect, it, vi } from 'vitest';
import type { Post, PostCommentsPage } from '@/types';
import PostCommentsPanel from './PostCommentsPanel';

const { postComments } = vi.hoisted(() => ({
  postComments: vi.fn(),
}));

vi.mock('@/services/api', () => ({
  apiService: {
    postComments,
    startPostCommentCollection: vi.fn(),
  },
}));
vi.mock('@umijs/max', () => ({
  history: { push: vi.fn() },
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => (
    <a href={to}>{children}</a>
  ),
}));

describe('PostCommentsPanel', () => {
  it('keeps the comment list in its own bounded scroll region and offers quick collection', async () => {
    postComments.mockResolvedValue({
      items: [
        {
          id: 1,
          post_id: 7,
          comment_id: 'comment-1',
          parent_comment_id: '',
          root_comment_id: 'comment-1',
          comment_type: 'root',
          is_reply_preview: 0,
          author_user_id: 'author-1',
          author_name: '评论作者',
          author_avatar_url: '',
          content: '评论正文',
          likes_count: 3,
          published_at: '2026-08-11T10:00:00Z',
          ip_location: '上海',
          platform_reply_count: 0,
          is_invalid: 0,
          page_number: 1,
          page_rank: 1,
          reply_previews: [],
        },
      ],
      page: 1,
      page_size: 20,
      total: 1,
      summary: {
        platform_comment_count: 1,
        root_comment_count: 1,
        reply_preview_count: 0,
        reply_count: 0,
        last_comments_fetched_at: null,
        latest_task: null,
        active_task: null,
        checkpoint: null,
      },
    } satisfies PostCommentsPage);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={client}>
        <App>
          <PostCommentsPanel post={{ id: 7, note_id: 'note-7' } as Post} />
        </App>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('评论正文')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: '评论列表' })).toHaveClass('post-comments-scroll');
    expect(screen.getByRole('button', { name: '快捷补充评论' })).toBeInTheDocument();
  });
});
