import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiService } from '@/services/api';
import type { Author } from '@/types';
import AuthorDetailDrawer from './AuthorDetailDrawer';

const { historyPush } = vi.hoisted(() => ({ historyPush: vi.fn() }));

vi.mock('@umijs/max', () => ({
  history: { push: historyPush },
}));

vi.mock('@/pages/Authors/Detail', () => ({
  default: ({ authorId, embedded }: { authorId: number; embedded: boolean }) => (
    <div data-testid="shared-author-detail" data-author-id={authorId} data-embedded={embedded}>
      共享作者详情
    </div>
  ),
}));

function author(): Author {
  return {
    id: 7,
    author_id: 'author-7',
    xhs_id: 'xhs-7',
    display_name: '作者七',
    profile_url: 'https://www.xiaohongshu.com/user/profile/author-7',
    bio: '',
    ip_location: '',
    followers_count: 100,
    following_count: 1,
    likes_collections_count: 200,
    avatar_url: '',
    avatar_local_path: '',
    first_seen_at: '',
    last_seen_at: '',
    last_profile_fetched_at: null,
    updated_at: '',
  };
}

function renderDrawer(children?: ReactNode) {
  vi.spyOn(apiService, 'author').mockResolvedValue(author());
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AuthorDetailDrawer authorId={7} onClose={vi.fn()} />
      {children}
    </QueryClientProvider>,
  );
}

describe('AuthorDetailDrawer', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    historyPush.mockReset();
  });

  it('reuses the author detail content and opens the full detail page in-app', async () => {
    renderDrawer();

    const sharedDetail = await screen.findByTestId('shared-author-detail');
    expect(sharedDetail).toHaveAttribute('data-author-id', '7');
    expect(sharedDetail).toHaveAttribute('data-embedded', 'true');

    fireEvent.click(screen.getByRole('button', { name: '查看完整详情' }));

    expect(historyPush).toHaveBeenCalledWith('/authors/7');
  });
});
