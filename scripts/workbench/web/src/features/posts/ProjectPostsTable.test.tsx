import { fireEvent, render, screen } from '@testing-library/react';
import type { TableProps } from 'antd';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import type { Post } from '@/types';
import ProjectPostsTable from './ProjectPostsTable';

vi.mock('@ant-design/pro-components', () => ({
  ProTable: ({
    columns,
    dataSource,
    headerTitle,
    rowSelection,
  }: {
    columns: Array<{
      title?: ReactNode;
      render?: (value: unknown, row: Post, index: number) => ReactNode;
    }>;
    dataSource: Post[];
    headerTitle?: ReactNode;
    rowSelection?: TableProps<Post>['rowSelection'];
  }) => {
    const actionColumn = columns.find((column) => column.title === '操作');
    const titleColumn = columns.find((column) => column.title === '帖子');
    const firstPost = dataSource[0];
    return (
      <section>
        <div data-testid="table-toolbar">{headerTitle}</div>
        <div data-testid="column-titles">
          {columns.map((column, index) => (
            <span key={String(index)}>{column.title}{index < columns.length - 1 ? '|' : null}</span>
          ))}
        </div>
        <div data-testid="post-order">{dataSource.map((post) => post.note_id).join('|')}</div>
        <div data-testid="preserve-selection">
          {String(rowSelection?.preserveSelectedRowKeys)}
        </div>
        {firstPost ? (
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
        ) : null}
        <div data-testid="action-cell">
          {firstPost ? actionColumn?.render?.(undefined, firstPost, 0) : null}
        </div>
        <div data-testid="title-cell">
          {firstPost ? titleColumn?.render?.(undefined, firstPost, 0) : null}
        </div>
      </section>
    );
  },
}));

vi.mock('./PostDetailUpdateControl', () => ({
  default: () => <button type="button">更新帖子详情</button>,
}));
vi.mock('./PostCommentCollectionAction', () => ({
  default: () => <button type="button">补充评论</button>,
}));

function post(id: number, noteId: string): Post {
  return {
    id,
    note_id: noteId,
    author_id: 1,
    author_name: '作者',
    external_author_id: 'author-1',
    title: `帖子 ${id}`,
    content: '',
    note_type: 'image',
    note_url: `https://www.xiaohongshu.com/explore/${noteId}`,
    cover_url: '',
    cover_local_path: '',
    publish_date: '',
    likes_count: id,
    favorites_count: 0,
    comments_count: 0,
    author_followers_count: 320,
    attention_score: 96,
    detail_level: 'card',
    updated_at: '',
    last_seen_at: '',
  };
}

describe('ProjectPostsTable', () => {
  it('hides the Note ID column and preserves the server-provided page order', () => {
    render(
      <ProjectPostsTable
        posts={[
          post(1, '100000010000000000000001'),
          post(2, '100000030000000000000003'),
          post(3, '100000020000000000000002'),
        ]}
        onOpen={vi.fn()}
        onLink={vi.fn()}
        onUnlink={vi.fn()}
        onVision={vi.fn()}
        projectId={1}
        onTaskCreated={vi.fn()}
      />,
    );

    expect(screen.getByTestId('column-titles')).not.toHaveTextContent('Note ID');
    const columnTitles = screen.getByTestId('column-titles').textContent?.split('|') ?? [];
    expect(columnTitles).toContain('信息完整度');
    expect(screen.getByTestId('column-titles')).toHaveTextContent('收藏');
    expect(screen.getByTestId('column-titles')).toHaveTextContent('评论');
    expect(screen.getByTestId('column-titles')).toHaveTextContent('发布时间');
    expect(screen.getByTestId('column-titles')).toHaveTextContent('关注分');
    expect(screen.getByTestId('column-titles')).toHaveTextContent('作者粉丝');
    expect(screen.getByTestId('column-titles')).toHaveTextContent('OCR');
    expect(screen.getByTestId('column-titles')).toHaveTextContent('图片理解');
    expect(columnTitles.indexOf('OCR')).toBe(
      columnTitles.indexOf('信息完整度') + 1,
    );
    expect(columnTitles.indexOf('图片理解')).toBe(
      columnTitles.indexOf('OCR') + 1,
    );
    expect(screen.getByRole('link', { name: /原文/ })).toHaveAttribute('target', '_blank');
    expect(screen.getByTestId('column-titles')).not.toHaveTextContent('详情');
    expect(screen.getByTestId('preserve-selection')).toHaveTextContent('true');
    expect(screen.getByTestId('post-order')).toHaveTextContent(
      '100000010000000000000001|100000030000000000000003|100000020000000000000002',
    );
  });

  it('supports selecting project posts and unlinking them', () => {
    const onUnlink = vi.fn();
    render(
      <ProjectPostsTable
        posts={[post(1, '100000010000000000000001')]}
        onOpen={vi.fn()}
        onLink={vi.fn()}
        onUnlink={onUnlink}
        onVision={vi.fn()}
        projectId={1}
        onTaskCreated={vi.fn()}
      />,
    );

    expect(screen.getByRole('button', { name: '取消关联' })).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox', { name: '选择第一篇帖子' }));
    fireEvent.click(screen.getByRole('button', { name: '取消关联，已选 1 篇' }));

    expect(onUnlink).toHaveBeenCalledWith([1]);
  });

  it('opens a project post through the current-page detail callback', () => {
    const onOpen = vi.fn();
    const firstPost = post(1, '100000010000000000000001');
    render(
      <ProjectPostsTable
        posts={[firstPost]}
        onOpen={onOpen}
        onLink={vi.fn()}
        onUnlink={vi.fn()}
        onVision={vi.fn()}
        projectId={1}
        onTaskCreated={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '帖子 1' }));
    expect(onOpen).toHaveBeenCalledWith(firstPost);
  });

  it('shows project-wide completion counts and lets users jump to pending work', () => {
    const onQueryChange = vi.fn();
    const onVision = vi.fn();
    render(
      <ProjectPostsTable
        posts={[post(1, '100000010000000000000001')]}
        onOpen={vi.fn()}
        onLink={vi.fn()}
        onUnlink={vi.fn()}
        onVision={onVision}
        projectId={1}
        onTaskCreated={vi.fn()}
        onQueryChange={onQueryChange}
        coverage={{
          total: 12,
          detailed: 7,
          preview: 5,
          ocr_available: 9,
          ocr_completed: 6,
          ocr_pending: 3,
          ocr_other: 3,
        }}
      />,
    );

    expect(screen.getByRole('button', { name: '查看信息完整度处理进度' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '查看OCR处理进度' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '查看信息完整度处理进度' }));
    expect(screen.getByText('已完成 7 / 12')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '查看待补全' }));
    expect(onQueryChange).toHaveBeenLastCalledWith(expect.objectContaining({
      detail: 'preview',
      ocr: 'all',
      page: 1,
    }));

    fireEvent.click(screen.getByRole('button', { name: '查看OCR处理进度' }));
    expect(screen.getByText('已完成 6 / 9')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '查看待 OCR' }));
    expect(onQueryChange).toHaveBeenLastCalledWith(expect.objectContaining({
      detail: 'all',
      ocr: 'pending',
      page: 1,
    }));

    fireEvent.click(screen.getByRole('button', { name: '去处理' }));
    expect(onVision).toHaveBeenCalledOnce();
  });
});
