import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App as AntApp } from 'antd';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiService } from '@/services/api';
import type { Report } from '@/types';
import ReportRunModal from './ReportRunModal';

const summaryReport: Report = {
  id: 31,
  project_id: 12,
  task_id: null,
  version: 4,
  report_type: 'data_summary',
  status: 'completed',
  title: '内容机会 数据摘要',
  summary_json: { schema_version: 5 },
  content_markdown: '',
  evidence_post_count: 101,
  evidence_author_count: 8,
  generated_at: '2026-08-12T08:00:00Z',
  generator_type: 'template',
  generator_version: 3,
  model: '',
  prompt_version: '',
  evidence_snapshot_json: {},
  generation_config_json: {},
};

function renderModal(postCount = 101, reports: Report[] = []) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AntApp>
        <ReportRunModal
          target={{ type: 'project', id: 12, name: '内容机会' }}
          status={{
            provider_available: true,
            post_count: postCount,
            author_count: 8,
            ocr_post_count: 60,
            vision_post_count: 30,
          }}
          reports={reports}
          open
          onClose={vi.fn()}
          onCreated={vi.fn()}
        />
      </AntApp>
    </QueryClientProvider>,
  );
}

describe('ReportRunModal', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('defaults to representative posts and the requested context sections', () => {
    renderModal();

    expect(screen.getByRole('switch', { name: '引用作者' })).toBeChecked();
    expect(screen.getByRole('switch', { name: '引用帖子' })).toBeChecked();
    expect(screen.getByRole('radio', { name: /有代表性的帖子 · 20%/ })).toBeChecked();
    expect(screen.getByText(/使用 20 篇/)).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /更多帖子 · 50%.*使用 51 篇/ })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: '基础信息' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: '正文' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'OCR 文本' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: '大模型理解文本' })).not.toBeChecked();
  });

  it('never allows both evidence sources to be switched off', () => {
    renderModal();

    fireEvent.click(screen.getByRole('switch', { name: '引用作者' }));
    expect(screen.getByRole('switch', { name: '引用作者' })).not.toBeChecked();
    expect(screen.getByRole('switch', { name: '引用帖子' })).toBeDisabled();

    fireEvent.click(screen.getByRole('switch', { name: '引用作者' }));
    fireEvent.click(screen.getByRole('switch', { name: '引用帖子' }));
    expect(screen.getByRole('switch', { name: '引用帖子' })).not.toBeChecked();
    expect(screen.getByRole('switch', { name: '引用作者' })).toBeDisabled();
  });

  it('submits the explicit context configuration', async () => {
    const startReport = vi.spyOn(apiService, 'startReport').mockResolvedValue({
      id: 'report-task', status: 'queued', url: '/#/tasks/report-task',
    });
    renderModal(10);

    fireEvent.click(screen.getByRole('button', { name: '确认生成' }));

    await waitFor(() => expect(startReport).toHaveBeenCalledWith(12, expect.objectContaining({
      sources: ['current_detail'],
      context_config: {
        authors: { enabled: true },
        posts: {
          enabled: true,
          selection_mode: 'representative',
          sections: ['basic', 'content', 'ocr'],
        },
      },
    })));
  });

  it('defaults to both sources when a data summary exists and submits its version', async () => {
    const startReport = vi.spyOn(apiService, 'startReport').mockResolvedValue({
      id: 'combined-report-task', status: 'queued', url: '/#/tasks/combined-report-task',
    });
    renderModal(101, [summaryReport]);

    expect(screen.getByRole('checkbox', { name: '引用数据摘要' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: '引用当前明细数据' })).toBeChecked();
    expect(screen.getByRole('combobox', { name: '数据摘要版本' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '确认生成' }));

    await waitFor(() => expect(startReport).toHaveBeenCalledWith(12, expect.objectContaining({
      sources: ['data_summary', 'current_detail'],
      data_summary_report_id: 31,
    })));
  });
});
