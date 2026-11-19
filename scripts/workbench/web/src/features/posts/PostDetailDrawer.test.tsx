import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { App as AntApp } from 'antd';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiService } from '@/services/api';
import type { Post } from '@/types';
import PostDetailDrawer from './PostDetailDrawer';

const post: Post = {
  id: 13,
  note_id: 'note-13',
  author_id: 2,
  author_name: 'Ai 林爻',
  external_author_id: 'author-2',
  title: '6分钟：普通人也能用上 Codex',
  content: '',
  note_type: 'video',
  note_url: 'https://www.xiaohongshu.com/explore/note-13',
  cover_url: '',
  cover_local_path: '/tmp/cover.webp',
  media_url: '/media/cover.webp',
  publish_date: '2026-07-31T06:23:10+00:00',
  likes_count: 45_000,
  favorites_count: null,
  comments_count: null,
  detail_level: 'card',
  popularity_level: '高热',
  sources: 'author-2',
  updated_at: '2026-07-10T16:55:43+00:00',
  last_seen_at: '2026-07-10T16:55:43+00:00',
  media: [
    {
      id: 1,
      post_id: 13,
      media_index: 0,
      media_type: 'cover',
      original_url: '',
      local_path: '/tmp/cover.webp',
      local_url: '/media/cover.webp',
      ocr_text: 'Codex 安装\n你一定能用上',
      ocr_engine: 'socai-ppocr',
      download_status: 'downloaded',
      updated_at: '2026-07-10T16:55:43+00:00',
    },
  ],
  vision: [
    {
      id: 1,
      post_id: 13,
      model: 'default',
      prompt_version: 'v1',
      analysis_json: {
        cover_hook: '低门槛标题降低学习阻力',
        visual_style: '实用教程封面',
        credibility_signals: ['真实产品界面'],
      },
      analyzed_at: '2026-07-10T21:00:49+00:00',
    },
  ],
};

describe('PostDetailDrawer', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the post as a readable evidence layout', async () => {
    vi.spyOn(apiService, 'post').mockResolvedValue(post);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <AntApp>
        <QueryClientProvider client={client}>
          <PostDetailDrawer summary={post} onClose={vi.fn()} />
        </QueryClientProvider>
      </AntApp>,
    );

    expect(await screen.findByTestId('post-detail-layout')).toBeInTheDocument();
    const dialog = screen.getByRole('dialog', { name: '帖子详情' });
    expect(dialog.closest('.post-detail-drawer-root')).not.toBeNull();
    expect(dialog.parentElement).toHaveStyle({ width: '960px' });
    expect(screen.getByRole('heading', { name: post.title })).toBeInTheDocument();
    expect(screen.getByText('2026-07-31 14:23')).toBeInTheDocument();
    expect(screen.getByLabelText('互动数据')).toHaveTextContent('45,000');
    fireEvent.click(screen.getByRole('tab', { name: '内容' }));
    expect(screen.getByText('当前保存的是列表卡片数据，尚未读取正文详情。')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: 'OCR 1' }));
    expect(screen.getByText(/Codex 安装/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: '图片理解 1' }));
    expect(screen.getByText('模型：Codex 默认模型')).toBeInTheDocument();
    expect(screen.getByText('Prompt：v1')).toBeInTheDocument();
    expect(screen.getByText('低门槛标题降低学习阻力')).toBeInTheDocument();
    expect(screen.getByText('真实产品界面')).toBeInTheDocument();
  });

  it('falls back to the note id and keeps incomplete evidence readable', async () => {
    const incomplete: Post = {
      ...post,
      title: '',
      media_url: undefined,
      content: '正文仍然可读',
      media: [],
      vision: [
        {
          id: 2,
          post_id: 13,
          model: 'default',
          prompt_version: 'v1',
          analysis_json: {
            problems: [`https://example.com/${'very-long-token-'.repeat(20)}`],
          },
          analyzed_at: '2026-07-10T21:00:49+00:00',
        },
      ],
    };
    vi.spyOn(apiService, 'post').mockResolvedValue(incomplete);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <AntApp>
        <QueryClientProvider client={client}>
          <PostDetailDrawer summary={incomplete} onClose={vi.fn()} />
        </QueryClientProvider>
      </AntApp>,
    );

    expect(await screen.findByRole('heading', { name: incomplete.note_id })).toBeInTheDocument();
    expect(screen.getByText('没有帖子封面')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: '内容' }));
    expect(screen.getByText('正文仍然可读')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: 'OCR' }));
    expect(screen.getByText('没有媒体或 OCR 结果')).toBeInTheDocument();
  });
});
