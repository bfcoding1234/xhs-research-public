import { fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App as AntApp } from 'antd';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { apiService } from '@/services/api';
import type { Report, ReportStatus } from '@/types';
import ReportPanel from './ReportPanel';

vi.mock('@ant-design/x-markdown', () => ({
  XMarkdown: ({ content }: { content: string }) => <div>{content}</div>,
}));

vi.mock('@ant-design/pro-components', () => {
  const ProCard = ({
    title,
    extra,
    children,
  }: {
    title?: ReactNode;
    extra?: ReactNode;
    children?: ReactNode;
  }) => (
    <section>
      <header>
        {title}
        {extra}
      </header>
      {children}
    </section>
  );
  return { ProCard };
});

const report: Report = {
  id: 17,
  project_id: 4,
  task_id: 'task-report',
  version: 3,
  report_type: 'author',
  status: 'completed',
  title: '带图片理解版本',
  summary_json: {},
  content_markdown: '# 报告正文',
  evidence_post_count: 23,
  evidence_author_count: 1,
  generated_at: '2026-07-11T00:00:00Z',
  generator_type: 'llm',
  generator_version: 2,
  model: 'default',
  prompt_version: 'v1',
  evidence_snapshot_json: {
    post_count: 23,
    author_count: 1,
    ocr_post_count: 23,
    vision_post_count: 0,
  },
  generation_config_json: { context_detail: 'detailed' },
};

const status: ReportStatus = {
  provider_available: true,
  post_count: 23,
  author_count: 1,
  ocr_post_count: 23,
  vision_post_count: 23,
};

const generatingReport: Report = {
  ...report,
  id: 18,
  task_id: 'task-generating',
  status: 'generating',
  title: '生成中的报告',
  content_markdown: '',
  generator_version: 3,
  evidence_post_count: 0,
  evidence_author_count: 0,
  evidence_snapshot_json: {},
};

describe('ReportPanel', () => {
  it('renders separate summary and large-model tabs without the duplicated current-data cards', () => {
    const summary = {
      ...report,
      id: 16,
      generator_type: 'template',
      generator_version: 1,
      title: '旧版数据摘要',
      content_markdown: '# Top 帖子',
      generation_config_json: { trigger: 'automatic', operation: 'ocr' },
    };
    const { container } = render(
      <ReportPanel
        reports={[report, summary]}
        status={status}
        onGenerate={vi.fn()}
        onGenerateSummary={vi.fn()}
      />,
    );

    expect(screen.getByRole('tab', { name: '数据摘要' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: '大模型报告' })).toBeInTheDocument();
    expect(screen.getByText('# Top 帖子')).toBeInTheDocument();
    expect(screen.getByText('自动 · OCR')).toBeInTheDocument();
    expect(container).not.toHaveTextContent('当前图片理解覆盖');
  });

  it('uses author wording and exposes data summaries for authors', () => {
    render(
      <ReportPanel
        reports={[{ ...report, project_id: null, author_id: 8 }]}
        status={status}
        onGenerate={vi.fn()}
        onGenerateSummary={vi.fn()}
        scopeLabel="作者"
      />,
    );

    expect(screen.getByText('作者报告')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '数据摘要' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '生成第一份数据摘要' })).toBeInTheDocument();
  });

  it('shows a generating version as disabled while keeping the latest completed report readable', () => {
    render(
      <ReportPanel
        reports={[generatingReport, report]}
        status={status}
        onGenerate={vi.fn()}
        onGenerateSummary={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('tab', { name: '大模型报告' }));
    expect(screen.getByText('# 报告正文')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /重新生成大模型报告/ })).toBeDisabled();
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '大模型报告历史版本' }));
    expect(screen.getByRole('option', { name: 'v3 · 生成中' })).toHaveAttribute(
      'aria-disabled',
      'true',
    );
  });

  it('shows a generating empty state when the first report has not completed yet', () => {
    render(
      <ReportPanel
        reports={[generatingReport]}
        status={status}
        onGenerate={vi.fn()}
        onGenerateSummary={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('tab', { name: '大模型报告' }));
    expect(screen.getByText('v3 · 生成中')).toBeInTheDocument();
    expect(screen.getByText('报告正在生成，完成后即可查看')).toBeInTheDocument();
    expect(screen.queryByText('生成第一份报告')).not.toBeInTheDocument();
  });

  it('shows generated HTML presentations above the long report body', async () => {
    vi.spyOn(apiService, 'reportPresentations').mockResolvedValue([{
      id: 9,
      project_report_id: report.id,
      author_report_id: null,
      task_id: 'presentation-task',
      version: 1,
      status: 'completed',
      title: '报告演示稿',
      page_mode: 'standard',
      slide_count: 10,
      model: 'default',
      prompt_version: 'report-presentation-v1',
      generation_config_json: {},
      generated_at: '2026-08-12T00:00:00Z',
    }]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <AntApp>
          <ReportPanel
            reports={[report]}
            status={status}
            target={{ type: 'project', id: 4 }}
            onPresentationCreated={vi.fn()}
            onGenerate={vi.fn()}
            onGenerateSummary={vi.fn()}
          />
        </AntApp>
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole('tab', { name: '大模型报告' }));
    const presentation = await screen.findByText('HTML 演示稿');
    const reportBody = screen.getByText('# 报告正文');
    expect(presentation.compareDocumentPosition(reportBody) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy();
  });
});
