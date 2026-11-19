import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { App } from 'antd';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiService } from '@/services/api';
import type { AppSettings, Author, Project } from '@/types';
import ProjectAuthorBulkUpdateModal from './ProjectAuthorBulkUpdateModal';

const project = {
  id: 4,
  name: '测试项目',
  slug: 'test-project',
  description: '',
  research_type: 'author',
  status: 'active',
  config_json: {},
} as Project;

const authors = [
  {
    id: 1,
    author_id: 'author-a',
    display_name: '作者甲',
    last_profile_fetched_at: null,
  },
] as Author[];

const settings = {
  default_discovery: 20,
  default_deep: 5,
  max_author_notes: 300,
} as AppSettings;

describe('ProjectAuthorBulkUpdateModal', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('uses the low-frequency author and batch delay defaults', async () => {
    const startProjectAuthorUpdates = vi
      .spyOn(apiService, 'startProjectAuthorUpdates')
      .mockResolvedValue({ id: 'task-1', status: 'queued', url: '/tasks/task-1' });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });

    render(
      <QueryClientProvider client={client}>
        <App>
          <ProjectAuthorBulkUpdateModal
            project={project}
            authors={authors}
            settings={settings}
            open
            onClose={vi.fn()}
            onCreated={vi.fn()}
          />
        </App>
      </QueryClientProvider>,
    );

    await waitFor(() =>
      expect(screen.getByLabelText('作者间隔最短秒数')).toHaveValue('1'),
    );
    expect(screen.getByLabelText('作者间隔最长秒数')).toHaveValue('3');
    expect(screen.getByLabelText('批次间隔最短秒数')).toHaveValue('2');
    expect(screen.getByLabelText('批次间隔最长秒数')).toHaveValue('5');

    fireEvent.click(screen.getByRole('button', { name: '创建更新任务' }));

    await waitFor(() => expect(startProjectAuthorUpdates).toHaveBeenCalledOnce());
    expect(startProjectAuthorUpdates.mock.calls[0]?.[1]).toMatchObject({
      batch_size: 10,
      author_delay_min_seconds: 1,
      author_delay_max_seconds: 3,
      batch_delay_min_seconds: 2,
      batch_delay_max_seconds: 5,
    });
  });
});
