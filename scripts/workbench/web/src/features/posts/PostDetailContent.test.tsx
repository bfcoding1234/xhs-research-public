import { fireEvent, render, screen } from '@testing-library/react';
import { App as AntApp } from 'antd';
import { describe, expect, it, vi } from 'vitest';
import type { Post } from '@/types';
import PostDetailContent from './PostDetailContent';

vi.mock('@umijs/max', () => ({
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => <a href={to}>{children}</a>,
}));
vi.mock('./PostCommentsPanel', () => ({ default: () => <div>评论模块</div> }));

const post: Post = {
  id: 1,
  note_id: 'note-1',
  author_id: 2,
  author_name: '小红书作者',
  external_author_id: 'author-2',
  title: '一篇很长的帖子标题',
  content: '正文内容',
  note_type: 'image',
  note_url: '',
  cover_url: '',
  cover_local_path: '',
  publish_date: '2026-08-01',
  likes_count: 10,
  favorites_count: 20,
  comments_count: 30,
  detail_level: 'media',
  updated_at: '2026-08-02',
  last_seen_at: '2026-08-02',
  media: [
    {
      id: 1,
      post_id: 1,
      media_index: 0,
      media_type: 'image',
      original_url: 'https://example.com/one.jpg',
      local_path: '',
      ocr_text: '第一张 OCR',
      ocr_engine: 'ocr',
      download_status: 'remote',
      updated_at: '2026-08-02',
    },
    {
      id: 2,
      post_id: 1,
      media_index: 1,
      media_type: 'cover',
      original_url: 'https://example.com/one.jpg',
      local_path: '/tmp/duplicated-cover.jpg',
      ocr_text: '重复的 OCR',
      ocr_engine: 'ocr',
      download_status: 'downloaded',
      updated_at: '2026-08-02',
    },
    {
      id: 3,
      post_id: 1,
      media_index: 2,
      media_type: 'image',
      original_url: 'https://example.com/two.jpg',
      local_path: '',
      ocr_text: '第一行 OCR\n第二行内容\n\n第三段内容',
      ocr_engine: 'ocr',
      download_status: 'remote',
      updated_at: '2026-08-02',
    },
  ],
  vision: [],
};

describe('PostDetailContent', () => {
  it('deduplicates the cover and keeps media navigation and OCR in sync', () => {
    render(
      <AntApp>
        <PostDetailContent mode="page" post={post} />
      </AntApp>,
    );

    expect(screen.getByText('10')).toBeInTheDocument();
    expect(screen.getByText('媒体 1')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '查看媒体 3' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '下一张' }));
    expect(screen.getByText('媒体 2')).toBeInTheDocument();
    fireEvent.keyDown(screen.getByLabelText('帖子媒体'), { key: 'ArrowLeft' });
    expect(screen.getByText('媒体 1')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '查看媒体 2' }));
    fireEvent.click(screen.getByRole('tab', { name: 'OCR 2' }));
    expect(screen.getByText('第一行 OCR第二行内容')).toBeInTheDocument();
    expect(screen.getByText('第三段内容')).toBeInTheDocument();
    expect(screen.getByText('正文内容')).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: '概览' })).not.toBeInTheDocument();
  });

  it('shows the full post content without an expand or collapse state', () => {
    const fullContent = Array.from({ length: 12 }, (_, index) => `正文第 ${index + 1} 行`).join('\n');
    const { container } = render(
      <AntApp>
        <PostDetailContent mode="page" post={{ ...post, content: fullContent }} />
      </AntApp>,
    );

    const content = container.querySelector('.post-detail-copy');
    expect(content).toHaveTextContent('正文第 1 行');
    expect(content).toHaveTextContent('正文第 12 行');
    expect(content).not.toHaveClass('ant-typography-ellipsis');
    expect(content).not.toHaveClass('ant-typography-ellipsis-multiple-line');
    expect(screen.queryByText(/展开|收起|expand|collapse/i)).not.toBeInTheDocument();
  });
});
