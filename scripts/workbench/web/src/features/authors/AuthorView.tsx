import {
  AppstoreOutlined,
  DownOutlined,
  UnorderedListOutlined,
  UserOutlined,
} from '@ant-design/icons';
import type { MenuProps, TableProps } from 'antd';
import { Avatar, Button, Card, Checkbox, Dropdown, List, Segmented, Select, Typography } from 'antd';
import { useMemo, useState } from 'react';
import type { ComponentProps, Key, ReactNode } from 'react';
import type { Author } from '@/types';
import { storedAuthorPostCount } from '@/utils/authors';
import { formatNumber } from '@/utils/format';
import './AuthorView.css';

export type AuthorViewMode = 'list' | 'card';
export type AuthorCardSort =
  | 'followers_desc'
  | 'followers_asc'
  | 'likes_desc'
  | 'posts_desc'
  | 'updated_desc'
  | 'name_asc';

export const DEFAULT_AUTHOR_VIEW_MODE: AuthorViewMode = 'card';

export function AuthorListHeader({
  title,
  view,
  onViewChange,
  query,
  actions,
  showViewLabel = false,
}: {
  title: ReactNode;
  view: AuthorViewMode;
  onViewChange: (value: AuthorViewMode) => void;
  query?: ReactNode;
  actions?: ReactNode;
  showViewLabel?: boolean;
}) {
  return (
    <div className="author-list-header">
      <Typography.Text className="author-list-header-title" strong>
        {title}
      </Typography.Text>
      <div className="author-list-header-tools">
        {query ? (
          <div className="author-toolbar-query-content">
            {query}
          </div>
        ) : null}
        {showViewLabel ? <Typography.Text type="secondary">视图</Typography.Text> : null}
        <AuthorViewSwitcher value={view} onChange={onViewChange} />
        {actions}
      </div>
    </div>
  );
}

export function AuthorToolbarActions({
  selectedCount,
  onClearSelection,
  children,
}: {
  selectedCount: number;
  onClearSelection?: () => void;
  children: ReactNode;
}) {
  const selectionMenu: MenuProps = {
    items:
      selectedCount > 0
        ? [{ key: 'clear', label: '取消选择' }]
        : [{ key: 'empty', label: '暂无可用操作', disabled: true }],
    onClick: ({ key }) => {
      if (key === 'clear') onClearSelection?.();
    },
  };

  return (
    <section className="author-toolbar-actions" aria-label="作者操作">
      <Dropdown
        menu={selectionMenu}
        placement="bottomLeft"
        trigger={['click']}
      >
        <Button
          type="text"
          className="author-toolbar-selection-trigger"
          aria-label={`已选 ${selectedCount} 位，打开选择操作`}
        >
          <span className="author-toolbar-selection" aria-live="polite">
            已选 <strong>{selectedCount}</strong> 位
          </span>
          <DownOutlined />
        </Button>
      </Dropdown>
      {children}
    </section>
  );
}

export function AuthorViewSwitcher({
  value,
  onChange,
}: {
  value: AuthorViewMode;
  onChange: (value: AuthorViewMode) => void;
}) {
  return (
    <Segmented
      aria-label="作者视图"
      value={value}
      onChange={(next) => onChange(next as AuthorViewMode)}
      options={[
        { value: 'list', label: '列表', icon: <UnorderedListOutlined /> },
        { value: 'card', label: '卡片', icon: <AppstoreOutlined /> },
      ]}
    />
  );
}

function toggleSelection(
  author: Author,
  selectedRowKeys: readonly Key[],
  dataSource: Author[],
  onChange: NonNullable<NonNullable<TableProps<Author>['rowSelection']>['onChange']>,
) {
  const nextKeys = new Set(selectedRowKeys);
  if (nextKeys.has(author.id)) {
    nextKeys.delete(author.id);
  } else {
    nextKeys.add(author.id);
  }
  const nextKeyList = [...nextKeys];
  onChange(nextKeyList, dataSource.filter((item) => nextKeys.has(item.id)), { type: 'multiple' });
}

function normalizePagination(
  pagination: TableProps<Author>['pagination'],
  dataSourceLength: number,
): ComponentProps<typeof List<Author>>['pagination'] {
  if (pagination === false) return false;
  const paginationConfig = pagination && typeof pagination === 'object' ? pagination : {};
  return {
    ...paginationConfig,
    total: Math.max(paginationConfig.total ?? 0, dataSourceLength),
  } as ComponentProps<typeof List<Author>>['pagination'];
}

function authorName(author: Author) {
  return String(author.display_name || author.author_id);
}

function numeric(value: unknown) {
  return Number(value) || 0;
}

export function sortAuthorsForCard(
  authors: Author[],
  sort: AuthorCardSort = 'followers_desc',
): Author[] {
  return [...authors].sort((left, right) => {
    let result = 0;
    if (sort === 'followers_desc') {
      result = numeric(right.followers_count) - numeric(left.followers_count);
    } else if (sort === 'followers_asc') {
      result = numeric(left.followers_count) - numeric(right.followers_count);
    } else if (sort === 'likes_desc') {
      result = numeric(right.likes_collections_count) - numeric(left.likes_collections_count);
    } else if (sort === 'posts_desc') {
      result = storedAuthorPostCount(right) - storedAuthorPostCount(left);
    } else if (sort === 'updated_desc') {
      result = Date.parse(right.updated_at || '') - Date.parse(left.updated_at || '');
      if (!Number.isFinite(result)) result = 0;
    }
    return result || authorName(left).localeCompare(authorName(right), 'zh-CN');
  });
}

export function AuthorCardGrid({
  dataSource,
  loading = false,
  pagination,
  rowSelection,
  onSelect,
  renderActions,
  toolbarActions,
  sorting,
}: {
  dataSource: Author[];
  loading?: TableProps<Author>['loading'];
  pagination?: TableProps<Author>['pagination'];
  rowSelection?: TableProps<Author>['rowSelection'];
  onSelect: (author: Author) => void;
  renderActions?: (author: Author) => ReactNode;
  toolbarActions?: ReactNode;
  sorting?: {
    sort: AuthorCardSort;
    onSortChange: (sort: AuthorCardSort) => void;
  };
}) {
  const selectedRowKeys = rowSelection?.selectedRowKeys ?? [];
  const selectionOnChange = rowSelection?.onChange;
  const [internalSort, setInternalSort] = useState<AuthorCardSort>('followers_desc');
  const sort = sorting?.sort ?? internalSort;
  const sortedDataSource = useMemo(
    () => sortAuthorsForCard(dataSource, sort),
    [dataSource, sort],
  );
  const paginationConfig = normalizePagination(pagination, sortedDataSource.length);
  const initialPagination = paginationConfig && typeof paginationConfig === 'object'
    ? paginationConfig
    : {};
  const [currentPage, setCurrentPage] = useState(
    Number(initialPagination.current ?? initialPagination.defaultCurrent ?? 1),
  );
  const [pageSize, setPageSize] = useState(
    Number(initialPagination.pageSize ?? initialPagination.defaultPageSize ?? 10),
  );
  const effectiveCurrentPage =
    paginationConfig === false
      ? 1
      : Math.min(currentPage, Math.max(1, Math.ceil(sortedDataSource.length / pageSize)));
  const currentPageAuthors =
    paginationConfig === false
      ? sortedDataSource
      : sortedDataSource.slice(
          (effectiveCurrentPage - 1) * pageSize,
          effectiveCurrentPage * pageSize,
        );
  const listPagination =
    paginationConfig === false
      ? false
      : {
          ...paginationConfig,
          current: effectiveCurrentPage,
          pageSize,
          onChange: (page: number, nextPageSize: number) => {
            setCurrentPage(page);
            setPageSize(nextPageSize);
            paginationConfig?.onChange?.(page, nextPageSize);
          },
        };
  const selectableAuthors = currentPageAuthors.filter(
    (author) => !rowSelection?.getCheckboxProps?.(author).disabled,
  );
  const selectedKeySet = new Set(selectedRowKeys);
  const selectedSelectableCount = selectableAuthors.filter((author) =>
    selectedKeySet.has(author.id),
  ).length;
  const allCurrentSelected =
    selectableAuthors.length > 0 && selectedSelectableCount === selectableAuthors.length;
  const someCurrentSelected = selectedSelectableCount > 0 && !allCurrentSelected;

  const toggleAllCurrent = () => {
    if (!selectionOnChange) return;
    const nextKeys = new Set(selectedRowKeys);
    for (const author of selectableAuthors) {
      if (allCurrentSelected) nextKeys.delete(author.id);
      else nextKeys.add(author.id);
    }
    const nextKeyList = [...nextKeys];
    selectionOnChange(
      nextKeyList,
      sortedDataSource.filter((author) => nextKeys.has(author.id)),
      { type: 'all' },
    );
  };

  return (
    <div className="author-card-view">
      <div className="author-card-toolbar">
        <div className="author-card-toolbar-main">
          {selectionOnChange ? (
            <Checkbox
              checked={allCurrentSelected}
              disabled={selectableAuthors.length === 0}
              indeterminate={someCurrentSelected}
              onChange={toggleAllCurrent}
            >
              全选当前页
            </Checkbox>
          ) : null}
          {toolbarActions}
        </div>
        <section className="author-card-control-group" aria-label="卡片排序选项">
          <span className="author-card-control-label">排序</span>
          <Select<AuthorCardSort>
            aria-label="卡片排序"
            value={sort}
            onChange={(value) => {
              setCurrentPage(1);
              if (sorting) sorting.onSortChange(value);
              else setInternalSort(value);
            }}
            options={[
              { value: 'followers_desc', label: '粉丝：从高到低' },
              { value: 'followers_asc', label: '粉丝：从低到高' },
              { value: 'likes_desc', label: '获赞：从高到低' },
              { value: 'posts_desc', label: '帖子：从多到少' },
              { value: 'updated_desc', label: '最近更新' },
              { value: 'name_asc', label: '名称：升序' },
            ]}
          />
        </section>
      </div>
      <List<Author>
        className="author-card-grid"
        dataSource={sortedDataSource}
        loading={loading}
        rowKey="id"
        grid={{ gutter: [16, 16], xs: 1, sm: 2, md: 3, lg: 3, xl: 4, xxl: 4 }}
        pagination={listPagination}
        renderItem={(author) => {
          const checkboxProps = rowSelection?.getCheckboxProps?.(author);
          const name = author.display_name || author.author_id;
          return (
            <List.Item>
              <Card className="author-card" size="small" hoverable>
                <div className="author-card-header">
                  {selectionOnChange ? (
                    <Checkbox
                      {...checkboxProps}
                      checked={selectedRowKeys.includes(author.id)}
                      aria-label={`选择${name}`}
                      onChange={() =>
                        toggleSelection(
                          author,
                          selectedRowKeys,
                          sortedDataSource,
                          selectionOnChange,
                        )
                      }
                    />
                  ) : null}
                  <Avatar
                    size={56}
                    src={author.avatar_local_url || author.avatar_url || undefined}
                    icon={<UserOutlined />}
                  />
                  <Button
                    type="link"
                    className="author-card-name"
                    onClick={() => onSelect(author)}
                  >
                    {name}
                  </Button>
                </div>
                <Typography.Paragraph
                  className="author-card-bio"
                  ellipsis={{ rows: 3, tooltip: author.bio || '暂无简介' }}
                >
                  {author.bio || '暂无简介'}
                </Typography.Paragraph>
                <div className="author-card-location">
                  <Typography.Text type="secondary">IP 属地</Typography.Text>
                  <Typography.Text>{author.ip_location || '—'}</Typography.Text>
                </div>
                <section className="author-card-stats" aria-label={`${name}基础数据`}>
                  <div>
                    <Typography.Text type="secondary">粉丝</Typography.Text>
                    <Typography.Text strong>{formatNumber(author.followers_count)}</Typography.Text>
                  </div>
                  <div>
                    <Typography.Text type="secondary">获赞</Typography.Text>
                    <Typography.Text strong>
                      {formatNumber(author.likes_collections_count)}
                    </Typography.Text>
                  </div>
                </section>
                {renderActions ? (
                  <div className="author-card-actions">{renderActions(author)}</div>
                ) : null}
              </Card>
            </List.Item>
          );
        }}
      />
    </div>
  );
}

export function createAuthorTableViewRender(
  view: AuthorViewMode,
  onSelect: (author: Author) => void,
  renderActions?: (author: Author) => ReactNode,
  rowSelection?: TableProps<Author>['rowSelection'],
  toolbarActions?: ReactNode,
  sorting?: {
    sort: AuthorCardSort;
    onSortChange: (sort: AuthorCardSort) => void;
  },
) {
  return (tableProps: TableProps<Author>, defaultDom: ReactNode) => {
    if (view === 'list') return defaultDom;
    return (
      <AuthorCardGrid
        dataSource={Array.from(tableProps.dataSource ?? [])}
        loading={tableProps.loading}
        pagination={tableProps.pagination}
        rowSelection={rowSelection ?? tableProps.rowSelection}
        onSelect={onSelect}
        renderActions={renderActions}
        toolbarActions={toolbarActions}
        sorting={sorting}
      />
    );
  };
}
