import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { App as AntApp } from 'antd';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiService } from '@/services/api';
import type { AppSettings, VisionStatus } from '@/types';
import VisionRunModal from './VisionRunModal';

vi.mock('@umijs/max', () => ({
  history: { push: vi.fn() },
}));

const target = {
  type: 'project' as const,
  id: 4,
  name: '测试项目',
};

const settings: AppSettings = {
  host: '127.0.0.1',
  port: 4320,
  collector: 'socai',
  collector_bin: 'socai',
  collectors: [
    { id: 'auto', label: '自动（多提供方协同）', binary: 'multiple', available: true, default: false, capabilities: [] },
    { id: 'socai', label: 'Socai', binary: 'socai', available: true, default: true, capabilities: [] },
    { id: 'xiaohongshu-cli', label: 'xiaohongshu-cli', binary: 'xhs', available: true, default: false, capabilities: [] },
  ],
  socai_bin: 'socai',
  xiaohongshu_cli_bin: 'xhs',
  xiaohongshu_cookie_source: 'auto',
  codex_bin: 'codex',
  data_dir: '/tmp/xhs',
  detail_ttl_days: 30,
  author_ttl_days: 7,
  max_author_notes: 300,
  max_keywords_per_task: 5,
  max_authors_per_task: 5,
  default_keyword_author_limit: 500,
  research_workers: 1,
  vision_workers: 1,
  report_workers: 1,
  default_discovery: 50,
  default_deep: 0,
  vision_analysis_mode: 'vision-selective',
  vision_analysis_ratio: 0.2,
  vision_analysis_count: 10,
  vision_analysis_max_count: 30,
  vision_analysis_batch_size: 5,
  vision_model: '',
  vision_reasoning_effort: 'default',
  vision_timeout_seconds: 600,
  post_delay_min_seconds: 3,
  post_delay_max_seconds: 5,
  batch_delay_min_seconds: 10,
  batch_delay_max_seconds: 20,
  report_prompt_templates: { chunk: '{{allowed_post_ids}}\n{{evidence_json}}', final: '{{evidence_json}}' },
  report_prompt_defaults: { chunk: '{{allowed_post_ids}}\n{{evidence_json}}', final: '{{evidence_json}}' },
  report_prompt_template_hash: 'prompt-hash',
};

const status: VisionStatus = {
  provider_available: true,
  available_posts: 20,
  analyzed_posts: 0,
  pending_posts: 20,
  ocr_provider_available: true,
  ocr_available_posts: 12,
  ocr_processed_posts: 2,
  ocr_pending_posts: 10,
  ocr_other_posts: 3,
  vision_scopes: {
    cover: { available_posts: 8, analyzed_posts: 2, pending_posts: 6, available_images: 8, analyzed_images: 2, pending_images: 6 },
    detail: { available_posts: 12, analyzed_posts: 3, pending_posts: 9, available_images: 20, analyzed_images: 4, pending_images: 16 },
  },
  ocr_scopes: {
    cover: { available_posts: 8, processed_posts: 2, pending_posts: 6, other_posts: 0, available_images: 8, processed_images: 2, pending_images: 6 },
    detail: { available_posts: 12, processed_posts: 3, pending_posts: 9, other_posts: 0, available_images: 20, processed_images: 4, pending_images: 16 },
  },
};

describe('VisionRunModal', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('defaults to OCR and places it before large-model understanding', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <AntApp>
        <QueryClientProvider client={client}>
          <VisionRunModal
            target={target}
            status={status}
            settings={settings}
            open
            onClose={vi.fn()}
            onCreated={vi.fn()}
          />
        </QueryClientProvider>
      </AntApp>,
    );

    const ocr = await screen.findByRole('radio', { name: 'OCR 识图' });
    const vision = screen.getByRole('radio', { name: '大模型理解' });
    expect(ocr).toBeChecked();
    expect(ocr.compareDocumentPosition(vision) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole('checkbox', { name: '封面图' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: '详情图片' })).not.toBeChecked();
    expect(screen.getByText('可处理图片')).toBeInTheDocument();
    expect(screen.getByText('OCR 已完成图片')).toBeInTheDocument();
    expect(screen.getByText('待处理帖子范围')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('checkbox', { name: '详情图片' }));
    fireEvent.click(vision);
    await waitFor(() => {
      const preview = screen.getByText('本次预计').closest('.ant-statistic');
      expect(preview).toHaveTextContent('15');
    });
  });

  it('does not call the API when a required numeric field is cleared', async () => {
    const startVision = vi.spyOn(apiService, 'startVision');
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <AntApp>
        <QueryClientProvider client={client}>
          <VisionRunModal
            target={target}
            status={status}
            settings={settings}
            open
            onClose={vi.fn()}
            onCreated={vi.fn()}
          />
        </QueryClientProvider>
      </AntApp>,
    );

    const ratio = await screen.findByLabelText('选择比例（%）');
    await waitFor(() => expect(ratio).toHaveValue('20'));
    fireEvent.change(ratio, { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: '确认并开始' }));

    expect(await screen.findByText('请输入选择比例')).toBeInTheDocument();
    expect(startVision).not.toHaveBeenCalled();
  });

  it('submits only fields used by vision-all after switching from an invalid selective form', async () => {
    const startVision = vi.spyOn(apiService, 'startVision').mockResolvedValue({
      id: 'vision-task',
      status: 'queued',
      url: '/tasks/vision-task',
    });
    const onCreated = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <AntApp>
        <QueryClientProvider client={client}>
          <VisionRunModal
            target={target}
            status={status}
            settings={settings}
            open
            onClose={vi.fn()}
            onCreated={onCreated}
          />
        </QueryClientProvider>
      </AntApp>,
    );

    const ratio = await screen.findByLabelText('选择比例（%）');
    await waitFor(() => expect(ratio).toHaveValue('20'));
    fireEvent.change(ratio, { target: { value: '' } });

    fireEvent.click(screen.getByRole('checkbox', { name: '详情图片' }));
    fireEvent.mouseDown(screen.getByLabelText('帖子选择'));
    fireEvent.click(await screen.findByText('优先分析全部未处理图片'));
    await waitFor(() =>
      expect(screen.queryByLabelText('选择比例（%）')).not.toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole('button', { name: '确认并开始' }));
    await waitFor(() =>
      expect(startVision).toHaveBeenCalledWith(4, {
        processing_method: 'ocr',
        image_scopes: ['cover', 'detail'],
        mode: 'vision-all',
        vision_batch_size: 5,
      }),
    );
    expect(onCreated).toHaveBeenCalledWith({
      id: 'vision-task',
      status: 'queued',
      url: '/tasks/vision-task',
    });
  });

  it('submits author targets through the author vision API', async () => {
    const startAuthorVision = vi.spyOn(apiService, 'startAuthorVision').mockResolvedValue({
      id: 'author-vision-task',
      status: 'queued',
      url: '/tasks/author-vision-task',
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <AntApp>
        <QueryClientProvider client={client}>
          <VisionRunModal
            target={{ type: 'author', id: 8, name: '作者一' }}
            status={status}
            settings={settings}
            open
            onClose={vi.fn()}
            onCreated={vi.fn()}
          />
        </QueryClientProvider>
      </AntApp>,
    );

    await screen.findByRole('radio', { name: 'OCR 识图' });
    fireEvent.click(screen.getByRole('button', { name: '确认并开始' }));

    await waitFor(() => expect(startAuthorVision).toHaveBeenCalledWith(8, {
      processing_method: 'ocr',
      image_scopes: ['cover'],
      mode: 'vision-selective',
      vision_ratio: 0.2,
      vision_count: 10,
      vision_max_count: 30,
      vision_batch_size: 5,
    }));
  });
});
