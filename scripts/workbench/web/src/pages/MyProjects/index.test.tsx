import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { App as AntApp } from 'antd';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiService } from '@/services/api';
import type { AppSettings, Author } from '@/types';
import MyPage from './index';

const { historyPush } = vi.hoisted(() => ({ historyPush: vi.fn() }));

vi.mock('@ant-design/pro-components', () => ({
  PageContainer: ({ children }: { children: React.ReactNode }) => <main>{children}</main>,
}));

vi.mock('@umijs/max', () => ({
  history: { push: historyPush },
}));

vi.mock('@/pages/Authors/Detail', () => ({
  default: (props: Record<string, unknown>) => (
    <div
      data-testid="fixed-author-detail"
      data-author-id={String(props.authorId)}
      data-route-base={String(props.routeBase)}
      data-show-back={String(props.showBack)}
      data-show-basic-info-update={String(props.showBasicInfoUpdate)}
      data-show-project-association={String(props.showProjectAssociation)}
    />
  ),
}));

function renderPage(myAuthorId: number | null, authors: Author[] = []) {
  vi.spyOn(apiService, 'settings').mockResolvedValue({
    my_author_id: myAuthorId,
  } as AppSettings);
  vi.spyOn(apiService, 'authors').mockResolvedValue(authors);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <AntApp>
      <QueryClientProvider client={client}>
        <MyPage />
      </QueryClientProvider>
    </AntApp>,
  );
}

describe('MyPage', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    historyPush.mockReset();
  });

  it('renders the configured author through the shared author detail page', async () => {
    renderPage(42);

    const detail = await screen.findByTestId('fixed-author-detail');
    expect(detail).toHaveAttribute('data-author-id', '42');
    expect(detail).toHaveAttribute('data-route-base', '/my-projects');
    expect(detail).toHaveAttribute('data-show-back', 'false');
    expect(detail).toHaveAttribute('data-show-basic-info-update', 'true');
    expect(detail).toHaveAttribute('data-show-project-association', 'false');
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  });

  it('sets an existing author without creating a scrape task', async () => {
    const setup = vi.spyOn(apiService, 'setupMyAuthor').mockResolvedValue({
      author_id: 7,
      task: null,
    });
    renderPage(null, [{
      id: 7,
      author_id: 'existing-author',
      display_name: '已有作者',
      xhs_id: 'xhs-7',
    } as Author]);

    const selector = await screen.findByRole('combobox');
    fireEvent.mouseDown(selector);
    fireEvent.click(await screen.findByText('已有作者 · 小红书号 xhs-7'));
    fireEvent.click(screen.getByRole('button', { name: '选择这位作者' }));

    await waitFor(() => expect(setup).toHaveBeenCalledWith({ author_id: 7 }, expect.anything()));
    expect(historyPush).not.toHaveBeenCalled();
  });

  it('starts the initial scrape when a new author ID is entered', async () => {
    const setup = vi.spyOn(apiService, 'setupMyAuthor').mockResolvedValue({
      author_id: 9,
      task: { id: 'task-initialize-me', status: 'queued', url: '/#/tasks/task-initialize-me' },
    });
    renderPage(null);

    fireEvent.change(await screen.findByRole('textbox', { name: '作者 ID' }), {
      target: { value: 'new-author-id' },
    });
    fireEvent.click(screen.getByRole('button', { name: '设置并开始抓取' }));

    await waitFor(() => expect(setup).toHaveBeenCalledWith(
      { external_author_id: 'new-author-id' },
      expect.anything(),
    ));
    expect(await screen.findByText('任务已创建')).toBeInTheDocument();
    expect(historyPush).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: /留在当前页/ }));
    expect(historyPush).not.toHaveBeenCalled();
  });
});
