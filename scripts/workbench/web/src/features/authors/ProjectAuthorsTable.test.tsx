import { fireEvent, render, screen } from '@testing-library/react';
import type { TableProps } from 'antd';
import { App } from 'antd';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import type { Author } from '@/types';
import ProjectAuthorsTable from './ProjectAuthorsTable';

vi.mock('@ant-design/pro-components', () => ({
  ProTable: ({
    columns,
    dataSource,
    rowSelection,
    tableViewRender,
    headerTitle,
    options,
    toolBarRender,
    tableAlertRender,
  }: {
    columns: Array<{ title?: string; sortOrder?: string | null }>;
    dataSource: Author[];
    rowSelection?: TableProps<Author>['rowSelection'];
    tableViewRender?: (props: TableProps<Author>, defaultDom: ReactNode) => ReactNode;
    headerTitle?: ReactNode;
    options?: false | object;
    toolBarRender?: false | (() => ReactNode[]);
    tableAlertRender?: false | (() => ReactNode);
  }) => {
    const activeView = tableViewRender?.(
      { dataSource, pagination: false, rowSelection },
      <div data-testid="author-list-view" />,
    );
    return (
      <section>
        <div data-testid="author-order">
          {dataSource.map((author) => author.author_id).join('|')}
        </div>
        <div data-testid="follower-sort">
          {columns.find((column) => column.title === '粉丝')?.sortOrder}
        </div>
        <div data-testid="author-column-titles">
          {columns.map((column) => column.title).join('|')}
        </div>
        <div data-testid="table-options">{options === false ? 'hidden' : 'visible'}</div>
        <div data-testid="table-alert">{tableAlertRender === false ? 'hidden' : 'visible'}</div>
        <div data-testid="preserve-selection">
          {String(rowSelection?.preserveSelectedRowKeys)}
        </div>
        <div data-testid="table-toolbar">{toolBarRender === false ? null : headerTitle}</div>
        {activeView}
      </section>
    );
  },
}));

function author(
  id: number,
  authorId: string,
  followers: number | null,
  relationType = 'task_added',
): Author {
  return {
    id,
    author_id: authorId,
    xhs_id: '',
    display_name: authorId,
    profile_url: '',
    bio: '',
    ip_location: '',
    followers_count: followers,
    following_count: 0,
    likes_collections_count: 0,
    avatar_url: '',
    avatar_local_path: '',
    first_seen_at: '',
    last_seen_at: '',
    last_profile_fetched_at: null,
    updated_at: '',
    relation_type: relationType,
  };
}

describe('ProjectAuthorsTable', () => {
  it('defaults to all authors and applies a business source from more filters', () => {
    render(
      <App>
        <ProjectAuthorsTable
          authors={[
            author(1, 'task', 100, 'task_added,research_source'),
            author(2, 'manual', 200, 'manual,post_author'),
            author(3, 'keyword', 300, 'keyword_post_author'),
          ]}
          onSelect={vi.fn()}
          onLink={vi.fn()}
          onUnlink={vi.fn()}
        />
      </App>,
    );

    expect(screen.getByTestId('author-order')).toHaveTextContent('keyword|manual|task');
    expect(screen.queryByRole('combobox', { name: '项目作者来源' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /更多筛选/ }));
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '项目作者来源' }));
    fireEvent.click(screen.getByRole('option', { name: '任务主动添加' }));
    fireEvent.click(screen.getByRole('button', { name: '确定' }));
    expect(screen.getByTestId('author-order')).toHaveTextContent('task');
    expect(screen.getByTestId('author-order')).not.toHaveTextContent('manual|keyword');

    fireEvent.click(screen.getByRole('button', { name: /更多筛选/ }));
    fireEvent.click(screen.getByRole('button', { name: '重置' }));
    expect(screen.getByTestId('author-order')).toHaveTextContent('keyword|manual|task');
  });

  it('inherits the global follower-count descending default', () => {
    render(
      <App>
        <ProjectAuthorsTable
          authors={[
            author(1, 'small', 120),
            author(2, 'large', 80_000),
            author(3, 'unknown', null),
          ]}
          onSelect={vi.fn()}
          onLink={vi.fn()}
          onUnlink={vi.fn()}
        />
      </App>,
    );

    expect(screen.getByTestId('author-order')).toHaveTextContent('large|small|unknown');
    expect(screen.getByTestId('follower-sort')).toHaveTextContent('descend');
    expect(screen.getByTestId('author-column-titles')).toHaveTextContent('IP 属地');
    expect(screen.getByRole('combobox', { name: '卡片排序' })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: '选择large' })).toBeInTheDocument();
    expect(screen.getByTestId('table-options')).toHaveTextContent('hidden');
    expect(screen.getByTestId('table-alert')).toHaveTextContent('hidden');
    expect(screen.getByTestId('preserve-selection')).toHaveTextContent('true');

    fireEvent.click(screen.getByText('列表'));

    expect(screen.getByTestId('author-list-view')).toBeInTheDocument();
    expect(screen.getByTestId('table-options')).toHaveTextContent('visible');
    expect(screen.getByTestId('table-toolbar')).toHaveTextContent('已选 0 位');
    expect(screen.getByRole('button', { name: '已选 0 位，打开选择操作' })).toBeInTheDocument();
  });

  it('keeps project card selection connected to shared batch actions', () => {
    render(
      <App>
        <ProjectAuthorsTable
          authors={[author(1, 'small', 120), author(2, 'large', 80_000)]}
          onSelect={vi.fn()}
          onLink={vi.fn()}
          onUnlink={vi.fn()}
        />
      </App>,
    );

    fireEvent.click(screen.getByRole('checkbox', { name: '选择large' }));
    fireEvent.click(screen.getByRole('checkbox', { name: '选择small' }));

    expect(screen.getByRole('region', { name: '作者操作' })).toHaveTextContent('已选 2 位');
    fireEvent.click(screen.getByRole('button', { name: '已选 2 位，打开选择操作' }));
    fireEvent.click(screen.getByText('取消选择'));
    expect(screen.getByRole('region', { name: '作者操作' })).toHaveTextContent('已选 0 位');

    fireEvent.click(screen.getByRole('checkbox', { name: '选择large' }));
    fireEvent.click(screen.getByRole('checkbox', { name: '选择small' }));
    const batchButton = screen.getByRole('button', { name: '批量更新，已选 2 位' });
    expect(batchButton).toBeEnabled();
    expect(batchButton).toHaveTextContent(/^批量更新\s*$/);
  });

  it('searches project authors like the global author list and unlinks selected authors', () => {
    const onUnlink = vi.fn();
    render(
      <App>
        <ProjectAuthorsTable
          authors={[
            { ...author(1, 'small', 120), display_name: '小作者', bio: '生活方式' },
            { ...author(2, 'large', 80_000), display_name: '大作者', xhs_id: 'xhs-large' },
          ]}
          onSelect={vi.fn()}
          onLink={vi.fn()}
          onUnlink={onUnlink}
        />
      </App>,
    );

    fireEvent.change(
      screen.getByRole('textbox', { name: '搜索项目作者名、作者 ID、小红书号或简介' }),
      { target: { value: 'xhs-large' } },
    );

    expect(screen.getByTestId('author-order')).toHaveTextContent('large');
    expect(screen.getByTestId('author-order')).not.toHaveTextContent('small');

    fireEvent.click(screen.getByRole('checkbox', { name: '选择大作者' }));
    fireEvent.click(screen.getByRole('button', { name: '取消关联，已选 1 位' }));

    expect(onUnlink).toHaveBeenCalledWith([2]);
  });

  it('exposes a project-level bulk update entry', () => {
    const onBulkUpdate = vi.fn();
    render(
      <App>
        <ProjectAuthorsTable
          authors={[author(1, 'small', 120)]}
          onSelect={vi.fn()}
          onLink={vi.fn()}
          onUnlink={vi.fn()}
          onBulkUpdate={onBulkUpdate}
        />
      </App>,
    );

    fireEvent.click(screen.getByRole('button', { name: '更新未更新作者' }));

    expect(onBulkUpdate).toHaveBeenCalledOnce();
  });
});
