import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { createPersistentRowSelection } from '@/features/selection/persistentRowSelection';
import {
  normalizePostCardPagination,
  postSortFromTable,
  postSortOrder,
  PostCardGrid,
  PostToolbarActions,
  sortPostsForCard,
  type PostCardData,
} from './PostView';

describe('post sorting', () => {
  it('maps controlled table sorting to the shared list query', () => {
    expect(postSortFromTable('likes', 'descend')).toBe('likes_desc');
    expect(postSortFromTable('likes_count', 'descend')).toBe('likes_desc');
    expect(postSortFromTable('publish_date', 'ascend')).toBe('published_asc');
    expect(postSortFromTable('attention_score', 'descend')).toBe('attention_desc');
    expect(postSortFromTable('title', 'ascend')).toBe('title_asc');
    expect(postSortFromTable('likes', null)).toBe('default');
    expect(postSortOrder('likes_desc', 'likes')).toBe('descend');
    expect(postSortOrder('likes_desc', 'title')).toBeNull();
    expect(postSortOrder('attention_asc', 'attention')).toBe('ascend');
  });

  it('sorts the complete local author-post collection in both directions', () => {
    const posts = [
      { id: 1, note_id: 'note-1', title: '乙', cover_url: '', likes_count: 5 },
      { id: 2, note_id: 'note-2', title: '甲', cover_url: '', likes_count: 50, attention_score: 90 },
    ];

    expect(sortPostsForCard(posts, 'likes_desc').map((post) => post.id)).toEqual([2, 1]);
    expect(sortPostsForCard(posts, 'likes_asc').map((post) => post.id)).toEqual([1, 2]);
    expect(sortPostsForCard(posts, 'title_asc').map((post) => post.id)).toEqual([2, 1]);
    expect(sortPostsForCard(posts, 'attention_desc').map((post) => post.id)).toEqual([2, 1]);
  });
});

describe('normalizePostCardPagination', () => {
  it('uses the local data source length when ProTable has no total', () => {
    expect(normalizePostCardPagination({ pageSize: 20, total: 0 }, 45)).toMatchObject({
      pageSize: 20,
      total: 45,
    });
  });
});

describe('PostCardGrid', () => {
  it('renders the cover and title and opens the selected post', () => {
    const onSelect = vi.fn();
    render(
      <PostCardGrid
        dataSource={[
          {
            id: 1,
            note_id: 'note-1',
            title: '帖子标题',
            cover_url: 'https://cdn.example/cover.webp',
            attention_score: 96,
            author_followers_count: 320,
          },
        ]}
        pagination={false}
        onSelect={onSelect}
      />,
    );

    expect(screen.getByAltText('帖子标题封面')).toBeInTheDocument();
    expect(screen.getByText('关注分 96')).toBeInTheDocument();
    expect(screen.getByText('作者粉丝 320')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '帖子标题' }));

    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }));

    onSelect.mockClear();
    fireEvent.click(screen.getByRole('button', { name: '查看帖子标题详情' }));

    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }));
  });

  it('keeps post selections when moving between card pages', () => {
    const posts: PostCardData[] = [
      { id: 1, note_id: 'note-1', title: '帖子一', cover_url: '', likes_count: 1 },
      { id: 2, note_id: 'note-2', title: '帖子二', cover_url: '', likes_count: 2 },
    ];

    function Harness() {
      const [selectedIds, setSelectedIds] = useState<number[]>([]);
      return (
        <>
          <output data-testid="selected-post-ids">{selectedIds.join(',')}</output>
          <PostCardGrid
            dataSource={posts}
            pagination={{ defaultPageSize: 1 }}
            rowSelection={createPersistentRowSelection<PostCardData>(
              selectedIds,
              setSelectedIds,
            )}
            sorting={{ sort: 'likes_asc', onSortChange: vi.fn() }}
          />
        </>
      );
    }

    render(<Harness />);
    fireEvent.click(screen.getByRole('checkbox', { name: '选择帖子一' }));
    fireEvent.click(screen.getByTitle('Next Page'));
    fireEvent.click(screen.getByRole('checkbox', { name: '选择帖子二' }));

    expect(screen.getByTestId('selected-post-ids')).toHaveTextContent('1,2');
  });
});

describe('PostToolbarActions', () => {
  it('keeps selection operations inside the selected-count dropdown', async () => {
    const onClearSelection = vi.fn();
    render(
      <PostToolbarActions selectedCount={2} onClearSelection={onClearSelection}>
        <button type="button">关联到项目</button>
      </PostToolbarActions>,
    );

    expect(screen.getByRole('button', { name: '关联到项目' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '已选 2 篇，打开选择操作' }));
    fireEvent.click(await screen.findByText('取消选择'));

    expect(onClearSelection).toHaveBeenCalledTimes(1);
  });
});
