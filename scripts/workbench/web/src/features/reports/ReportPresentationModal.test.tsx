import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App as AntApp } from 'antd';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiService } from '@/services/api';
import type { Report } from '@/types';
import ReportPresentationModal from './ReportPresentationModal';

const report: Report = {
  id: 17,
  project_id: 4,
  task_id: 'report-task',
  version: 3,
  report_type: 'keyword',
  status: 'completed',
  title: '内容机会报告',
  summary_json: {},
  content_markdown: '# 报告正文',
  evidence_post_count: 23,
  evidence_author_count: 8,
  generated_at: '2026-08-12T08:00:00Z',
  generator_type: 'llm',
  generator_version: 2,
  model: 'default',
  prompt_version: 'v1',
  evidence_snapshot_json: {},
  generation_config_json: {},
};

describe('ReportPresentationModal', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('creates a standard HTML presentation from the selected report version', async () => {
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const start = vi.spyOn(apiService, 'startReportPresentation').mockResolvedValue({
      id: 'presentation-task', status: 'queued', url: '/#/tasks/presentation-task',
    });
    const onCreated = vi.fn();
    render(
      <QueryClientProvider client={client}>
        <AntApp>
          <ReportPresentationModal
            target={{ type: 'project', id: 4 }}
            report={report}
            open
            onClose={vi.fn()}
            onCreated={onCreated}
          />
        </AntApp>
      </QueryClientProvider>,
    );

    fireEvent.change(screen.getByRole('textbox', { name: '补充要求' }), {
      target: { value: '面向管理层汇报' },
    });
    fireEvent.click(screen.getByRole('button', { name: '确认制作' }));

    await waitFor(() => expect(start).toHaveBeenCalledWith(
      { type: 'project', id: 4 },
      17,
      {
        title: '内容机会报告 演示稿',
        page_mode: 'standard',
        instructions: '面向管理层汇报',
      },
    ));
    expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ id: 'presentation-task' }));
  });
});
