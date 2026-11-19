import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { createPersistentRowSelection } from '@/features/selection/persistentRowSelection';
import type { Author } from '@/types';
import {
  AuthorCardGrid,
  AuthorListHeader,
  AuthorToolbarActions,
  AuthorViewSwitcher,
  DEFAULT_AUTHOR_VIEW_MODE,
  sortAuthorsForCard,
} from './AuthorView';

const author: Author = {
  id: 8,
  author_id: 'author-8',
  xhs_id: '',
  display_name: '增长研究员',
  profile_url: '',
  bio: '分享内容增长、AI 产品与用户研究。',
  ip_location: '上海',
  followers_count: 12_345,
  following_count: null,
  likes_collections_count: 67_890,
  avatar_url: '',
  avatar_local_path: '',
  first_seen_at: '',
  last_seen_at: '',
  last_profile_fetched_at: null,
  updated_at: '',
};

describe('AuthorView', () => {
  it('uses the card view by default across author lists', () => {
    expect(DEFAULT_AUTHOR_VIEW_MODE).toBe('card');
  });

  it('keeps the compact query and view switch in the list header', () => {
    const onClearSelection = vi.fn();
    render(
      <>
        <AuthorListHeader
          title="全部作者（2）"
          view="card"
          onViewChange={vi.fn()}
          query={<input aria-label="搜索作者" />}
        />
        <AuthorToolbarActions
          selectedCount={2}
          onClearSelection={onClearSelection}
        >
          <button type="button">批量更新</button>
        </AuthorToolbarActions>
      </>,
    );

    expect(screen.getByText('全部作者（2）')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: '搜索作者' })).toBeInTheDocument();
    expect(screen.getByRole('radiogroup', { name: '作者视图' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: '作者操作' })).toHaveTextContent('已选 2 位');

    fireEvent.click(screen.getByRole('button', { name: '已选 2 位，打开选择操作' }));
    fireEvent.click(screen.getByText('取消选择'));

    expect(onClearSelection).toHaveBeenCalled();
  });

  it('renders the requested author basics in cards', () => {
    render(<AuthorCardGrid dataSource={[author]} onSelect={vi.fn()} />);

    expect(screen.getByText('增长研究员')).toBeInTheDocument();
    expect(screen.getByText('分享内容增长、AI 产品与用户研究。')).toBeInTheDocument();
    expect(screen.getByText('IP 属地')).toBeInTheDocument();
    expect(screen.getByText('上海')).toBeInTheDocument();
    expect(screen.getByLabelText('增长研究员基础数据')).toHaveTextContent('粉丝12,345获赞67,890');
  });

  it('supports selecting all authors on the current card page', () => {
    const onChange = vi.fn();
    const secondAuthor = {
      ...author,
      id: 9,
      author_id: 'author-9',
      display_name: '产品研究员',
      followers_count: 1,
    };

    render(
      <AuthorCardGrid
        dataSource={[author, secondAuthor]}
        onSelect={vi.fn()}
        pagination={{ defaultPageSize: 1 }}
        rowSelection={{ selectedRowKeys: [], onChange }}
      />,
    );

    fireEvent.click(screen.getByRole('checkbox', { name: '全选当前页' }));

    expect(onChange).toHaveBeenCalledWith(
      [8],
      [author],
      { type: 'all' },
    );
  });

  it('keeps author selections when moving between card pages', () => {
    const secondAuthor = {
      ...author,
      id: 9,
      author_id: 'author-9',
      display_name: '产品研究员',
      followers_count: 1,
    };

    function Harness() {
      const [selectedIds, setSelectedIds] = useState<number[]>([]);
      return (
        <>
          <output data-testid="selected-author-ids">{selectedIds.join(',')}</output>
          <AuthorCardGrid
            dataSource={[author, secondAuthor]}
            onSelect={vi.fn()}
            pagination={{ defaultPageSize: 1 }}
            rowSelection={createPersistentRowSelection(selectedIds, setSelectedIds)}
          />
        </>
      );
    }

    render(<Harness />);
    fireEvent.click(screen.getByRole('checkbox', { name: '选择增长研究员' }));
    fireEvent.click(screen.getByTitle('Next Page'));
    fireEvent.click(screen.getByRole('checkbox', { name: '选择产品研究员' }));

    expect(screen.getByTestId('selected-author-ids')).toHaveTextContent('8,9');
  });

  it('sorts card data by the selected author metric', () => {
    const popular = { ...author, id: 9, display_name: '高赞作者', likes_collections_count: 999_999 };

    expect(sortAuthorsForCard([author, popular], 'likes_desc').map((item) => item.id)).toEqual([
      9, 8,
    ]);
  });

  it('switches between the list and card modes', () => {
    const onChange = vi.fn();
    render(<AuthorViewSwitcher value="list" onChange={onChange} />);

    fireEvent.click(screen.getByText('卡片'));

    expect(onChange).toHaveBeenCalledWith('card');
  });
});
