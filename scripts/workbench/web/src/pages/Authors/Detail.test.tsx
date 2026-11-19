import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { App as AntApp } from 'antd';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiService } from '@/services/api';
import type { AppSettings, Author, AuthorPost, VisionStatus } from '@/types';
import AuthorDetailPage, { type AuthorDetailPageProps } from './Detail';

const { historyPush } = vi.hoisted(() => ({ historyPush: vi.fn() }));

vi.mock('@umijs/max', () => ({
  history: { push: historyPush },
  Link: ({ to, children }: { to: string; children: ReactNode }) => <a href={to}>{children}</a>,
  useLocation: () => ({ pathname: '/authors/1/posts' }),
  useParams: () => ({ id: '1', tab: 'posts' }),
}));

vi.mock('@ant-design/pro-components', () => ({
  PageContainer: ({ children, title }: { children: ReactNode; title?: ReactNode }) => (
    <main>
      <h1>{title}</h1>
      {children}
    </main>
  ),
  ProTable: ({
    columns,
    dataSource,
    rowSelection,
    headerTitle,
    toolbar,
  }: {
    columns: Array<{
      title?: ReactNode;
      render?: (value: unknown, row: AuthorPost, index: number) => ReactNode;
    }>;
    dataSource: AuthorPost[];
    headerTitle?: ReactNode;
    rowSelection?: {
      selectedRowKeys?: React.Key[];
      onChange?: (
        keys: React.Key[],
        rows: NonNullable<Author['posts']>,
        info: { type: string },
      ) => void;
    };
    toolbar?: { actions?: ReactNode[] };
  }) => {
    const actionColumn = columns.find((column) => column.title === '操作');
    const firstPost = dataSource[0];
    return (
      <section>
        <div data-testid="header-title">{headerTitle}</div>
        <div data-testid="toolbar-actions">{toolbar?.actions}</div>
        {firstPost ? (
          <>
            <label>
              <input
                aria-label="选择第一篇帖子"
                checked={rowSelection?.selectedRowKeys?.includes(firstPost.id)}
                onChange={(event) =>
                  rowSelection?.onChange?.(
                    event.currentTarget.checked ? [firstPost.id] : [],
                    event.currentTarget.checked ? [firstPost] : [],
                    { type: 'single' },
                  )
                }
                type="checkbox"
              />
              选择第一篇帖子
            </label>
            <div data-testid="action-cell">{actionColumn?.render?.(undefined, firstPost, 0)}</div>
          </>
        ) : null}
      </section>
    );
  },
}));

vi.mock('@/features/references/AddToProjectModal', () => ({
  default: ({
    open,
    entityType,
    entityIds,
  }: {
    open: boolean;
    entityType: string;
    entityIds: number[];
  }) =>
    open ? (
      <div
        data-testid="add-to-project-modal"
        data-entity-type={entityType}
        data-entity-ids={entityIds.join(',')}
      />
    ) : null,
}));

vi.mock('@/features/posts/PostCover', () => ({
  default: ({ alt }: { alt: string }) => <img alt={alt} />,
}));

vi.mock('@/features/posts/PostOriginalLink', () => ({
  default: () => <a href="https://www.xiaohongshu.com/explore/note-1">原文</a>,
}));

vi.mock('@/features/authors/AuthorUpdateModal', () => ({
  buildAuthorBasicInfoUpdateConfiguration: () => ({ source: { author_ids: ['author-1'] } }),
  default: () => null,
}));

vi.mock('@/features/reports/ReportPanel', () => ({ default: () => null }));
vi.mock('@/features/reports/ReportRunModal', () => ({ default: () => null }));
vi.mock('@/features/vision/VisionRunModal', () => ({
  default: ({ open }: { open: boolean }) => open ? <div data-testid="vision-run-modal" /> : null,
}));
vi.mock('@/components/TaskCreatedModal', () => ({ default: () => null }));

function author(): Author {
  return {
    id: 1,
    author_id: 'author-1',
    xhs_id: '',
    display_name: '作者一',
    profile_url: '',
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
    posts: [
      {
        id: 11,
        note_id: 'note-11',
        title: '作者帖子',
        note_url: 'https://www.xiaohongshu.com/explore/note-11',
        cover_url: '',
        cover_local_path: '',
        likes_count: 1,
        publish_date: '',
        detail_level: 'card',
      },
    ],
    projects: [],
  };
}

function renderPage(props: AuthorDetailPageProps = {}) {
  vi.spyOn(apiService, 'author').mockResolvedValue(author());
  vi.spyOn(apiService, 'authorReports').mockResolvedValue([]);
  vi.spyOn(apiService, 'settings').mockResolvedValue({} as AppSettings);
  vi.spyOn(apiService, 'authorVisionStatus').mockResolvedValue({
    provider_available: true,
    available_posts: 1,
    analyzed_posts: 0,
    pending_posts: 1,
  } as VisionStatus);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <AntApp>
      <QueryClientProvider client={client}>
        <AuthorDetailPage {...props} />
      </QueryClientProvider>
    </AntApp>,
  );
}

describe('AuthorDetailPage posts', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    historyPush.mockReset();
  });

  it('allows author posts to be selected and linked to a project', async () => {
    renderPage();

    expect(await screen.findAllByText('作者一')).toHaveLength(2);
    const batchLink = screen.getByRole('button', { name: /关联到项目/ });
    expect(batchLink).toBeDisabled();

    fireEvent.click(screen.getByRole('checkbox', { name: '选择第一篇帖子' }));

    const selectedBatchLink = screen.getByRole('button', {
      name: '关联到项目，已选 1 篇',
    });
    expect(selectedBatchLink).toBeEnabled();
    fireEvent.click(selectedBatchLink);

    await waitFor(() =>
      expect(screen.getByTestId('add-to-project-modal')).toHaveAttribute(
        'data-entity-type',
        'post',
      ),
    );
    expect(screen.getByTestId('add-to-project-modal')).toHaveAttribute('data-entity-ids', '11');
  });

  it('links a single author post from the operation column', async () => {
    renderPage();

    expect(await screen.findAllByText('作者一')).toHaveLength(2);
    fireEvent.click(
      within(screen.getByTestId('action-cell')).getByRole('button', { name: /关联$/ }),
    );

    await waitFor(() =>
      expect(screen.getByTestId('add-to-project-modal')).toHaveAttribute(
        'data-entity-type',
        'post',
      ),
    );
    expect(screen.getByTestId('add-to-project-modal')).toHaveAttribute('data-entity-ids', '11');
  });

  it('opens image understanding for author posts', async () => {
    renderPage();

    const button = await screen.findByRole('button', { name: /补充图片理解/ });
    expect(button).toBeEnabled();
    fireEvent.click(button);

    expect(screen.getByTestId('vision-run-modal')).toBeInTheDocument();
  });

  it('switches embedded tabs without leaving the current page', async () => {
    renderPage({ authorId: 1, embedded: true });

    expect(await screen.findAllByText('作者一')).toHaveLength(1);
    fireEvent.click(screen.getByRole('tab', { name: '报告 0' }));

    expect(historyPush).not.toHaveBeenCalled();
  });
});
