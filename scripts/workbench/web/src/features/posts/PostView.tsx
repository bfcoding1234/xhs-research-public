import {
  AppstoreOutlined,
  DownOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons';
import type { MenuProps, TableProps } from 'antd';
import { Button, Card, Checkbox, Dropdown, List, Segmented, Select, Typography } from 'antd';
import { useMemo, useState } from 'react';
import type { ComponentProps, Key, ReactNode } from 'react';
import type { PostSort } from '@/types';
import { formatNumber } from '@/utils/format';
import { sortByNoteIdPrefixDesc } from './noteOrder';
import PostCover from './PostCover';
import './PostView.css';

export type PostViewMode = 'list' | 'card';
export type PostCardSort = PostSort;

export const POST_SORT_OPTIONS: Array<{ value: PostSort; label: string }> = [
  { value: 'default', label: '默认排序' },
  { value: 'likes_desc', label: '点赞：从高到低' },
  { value: 'likes_asc', label: '点赞：从低到高' },
  { value: 'favorites_desc', label: '收藏：从高到低' },
  { value: 'favorites_asc', label: '收藏：从低到高' },
  { value: 'comments_desc', label: '评论：从高到低' },
  { value: 'comments_asc', label: '评论：从低到高' },
  { value: 'published_desc', label: '发布时间：从新到旧' },
  { value: 'published_asc', label: '发布时间：从旧到新' },
  { value: 'updated_desc', label: '更新时间：从新到旧' },
  { value: 'updated_asc', label: '更新时间：从旧到新' },
  { value: 'title_asc', label: '标题：升序' },
  { value: 'title_desc', label: '标题：降序' },
];

export const PROJECT_POST_SORT_OPTIONS: Array<{ value: PostSort; label: string }> = [
  ...POST_SORT_OPTIONS,
  { value: 'attention_desc', label: '关注分：从高到低' },
  { value: 'attention_asc', label: '关注分：从低到高' },
  { value: 'popularity_desc', label: '热度：从高到低' },
  { value: 'popularity_asc', label: '热度：从低到高' },
];

export const GLOBAL_POST_SORT_OPTIONS: Array<{ value: PostSort; label: string }> = [
  ...POST_SORT_OPTIONS,
  { value: 'project_count_desc', label: '关联项目：从多到少' },
  { value: 'project_count_asc', label: '关联项目：从少到多' },
];

export type SortOrder = 'ascend' | 'descend' | null;

export function postSortOrder(sort: PostSort, field: string): SortOrder {
  if (!sort.startsWith(`${field}_`)) return null;
  return sort.endsWith('_asc') ? 'ascend' : 'descend';
}

export function postSortFromTable(field: unknown, order?: SortOrder): PostSort {
  if (!order) return 'default';
  const raw = String(field || '');
  const normalized = {
    likes_count: 'likes',
    favorites_count: 'favorites',
    comments_count: 'comments',
    publish_date: 'published',
    updated_at: 'updated',
    popularity_level: 'popularity',
    attention_score: 'attention',
  }[raw] ?? raw;
  const fields = new Set([
    'title',
    'likes',
    'favorites',
    'comments',
    'published',
    'updated',
    'popularity',
    'attention',
    'project_count',
  ]);
  if (!fields.has(normalized)) return 'default';
  return `${normalized}_${order === 'ascend' ? 'asc' : 'desc'}` as PostSort;
}

export interface PostCardData {
  id: number;
  note_id: string;
  title: string;
  cover_url: string;
  media_url?: string;
  media_remote_url?: string;
  note_url?: string;
  author_name?: string;
  external_author_id?: string;
  note_type?: string;
  likes_count?: number | null;
  favorites_count?: number | null;
  comments_count?: number | null;
  publish_date?: string;
  updated_at?: string;
  popularity_percentile?: number | null;
  author_followers_count?: number | null;
  attention_score?: number | null;
  project_count?: number | null;
}

export const DEFAULT_POST_VIEW_MODE: PostViewMode = 'list';

export function PostListHeader({
  title,
  view,
  onViewChange,
  query,
  showViewLabel = false,
}: {
  title: ReactNode;
  view: PostViewMode;
  onViewChange: (value: PostViewMode) => void;
  query?: ReactNode;
  showViewLabel?: boolean;
}) {
  return (
    <div className="post-list-header">
      <Typography.Text className="post-list-header-title" strong>
        {title}
      </Typography.Text>
      <div className="post-list-header-tools">
        {query ? <div className="post-toolbar-query-content">{query}</div> : null}
        {showViewLabel ? <Typography.Text type="secondary">视图</Typography.Text> : null}
        <PostViewSwitcher value={view} onChange={onViewChange} />
      </div>
    </div>
  );
}

export function PostToolbarActions({
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
    <section className="post-toolbar-actions" aria-label="帖子操作">
      <Dropdown
        menu={selectionMenu}
        placement="bottomLeft"
        trigger={['click']}
      >
        <Button
          type="text"
          className="post-toolbar-selection-trigger"
          aria-label={`已选 ${selectedCount} 篇，打开选择操作`}
        >
          <span className="post-toolbar-selection" aria-live="polite">
            已选 <strong>{selectedCount}</strong> 篇
          </span>
          <DownOutlined />
        </Button>
      </Dropdown>
      {children}
    </section>
  );
}

export function PostViewSwitcher({
  value,
  onChange,
}: {
  value: PostViewMode;
  onChange: (value: PostViewMode) => void;
}) {
  return (
    <Segmented
      aria-label="帖子视图"
      value={value}
      onChange={(next) => onChange(next as PostViewMode)}
      options={[
        { value: 'list', label: '列表', icon: <UnorderedListOutlined /> },
        { value: 'card', label: '卡片', icon: <AppstoreOutlined /> },
      ]}
    />
  );
}

function postTitle(post: PostCardData) {
  return String(post.title || post.note_id);
}

function numeric(value: unknown) {
  return Number(value) || 0;
}

function dateValue(value: unknown) {
  const result = Date.parse(String(value || ''));
  return Number.isFinite(result) ? result : 0;
}

export function sortPostsForCard<T extends PostCardData>(
  posts: T[],
  sort: PostCardSort = 'default',
): T[] {
  if (sort === 'default') return sortByNoteIdPrefixDesc(posts);
  return [...posts].sort((left, right) => {
    let result = 0;
    const direction = sort.endsWith('_asc') ? 1 : -1;
    if (sort.startsWith('title_')) {
      result = postTitle(left).localeCompare(postTitle(right), 'zh-CN') * direction;
    } else if (sort.startsWith('likes_')) {
      result = (numeric(left.likes_count) - numeric(right.likes_count)) * direction;
    } else if (sort.startsWith('favorites_')) {
      result = (numeric(left.favorites_count) - numeric(right.favorites_count)) * direction;
    } else if (sort.startsWith('comments_')) {
      result = (numeric(left.comments_count) - numeric(right.comments_count)) * direction;
    } else if (sort.startsWith('published_')) {
      result = (dateValue(left.publish_date) - dateValue(right.publish_date)) * direction;
    } else if (sort.startsWith('updated_')) {
      result = (dateValue(left.updated_at) - dateValue(right.updated_at)) * direction;
    } else if (sort.startsWith('popularity_')) {
      result =
        (numeric(left.popularity_percentile) - numeric(right.popularity_percentile)) * direction;
    } else if (sort.startsWith('attention_')) {
      result = (numeric(left.attention_score) - numeric(right.attention_score)) * direction;
    } else if (sort.startsWith('project_count_')) {
      result = (numeric(left.project_count) - numeric(right.project_count)) * direction;
    }
    return result || postTitle(left).localeCompare(postTitle(right), 'zh-CN');
  });
}

function toggleSelection<T extends PostCardData>(
  post: T,
  selectedRowKeys: readonly Key[],
  dataSource: T[],
  onChange: NonNullable<NonNullable<TableProps<T>['rowSelection']>['onChange']>,
) {
  const nextKeys = new Set(selectedRowKeys);
  if (nextKeys.has(post.id)) {
    nextKeys.delete(post.id);
  } else {
    nextKeys.add(post.id);
  }
  const nextKeyList = [...nextKeys];
  onChange(nextKeyList, dataSource.filter((item) => nextKeys.has(item.id)), { type: 'multiple' });
}

export function normalizePostCardPagination<T extends PostCardData>(
  pagination: TableProps<T>['pagination'],
  dataSourceLength: number,
): ComponentProps<typeof List<T>>['pagination'] {
  if (pagination === false) return false;

  const paginationConfig = pagination && typeof pagination === 'object' ? pagination : {};
  return {
    ...paginationConfig,
    total: Math.max(paginationConfig.total ?? 0, dataSourceLength),
  } as ComponentProps<typeof List<T>>['pagination'];
}

function PostCardStats<T extends PostCardData>({ post }: { post: T }) {
  return (
    <section className="post-card-stats" aria-label={`${postTitle(post)}基础数据`}>
      <div>
        <Typography.Text type="secondary">点赞</Typography.Text>
        <Typography.Text strong>{formatNumber(post.likes_count)}</Typography.Text>
      </div>
      <div>
        <Typography.Text type="secondary">收藏</Typography.Text>
        <Typography.Text strong>{formatNumber(post.favorites_count)}</Typography.Text>
      </div>
      <div>
        <Typography.Text type="secondary">评论</Typography.Text>
        <Typography.Text strong>{formatNumber(post.comments_count)}</Typography.Text>
      </div>
    </section>
  );
}

export function PostCardGrid<T extends PostCardData>({
  dataSource,
  loading = false,
  pagination,
  rowSelection,
  onSelect,
  renderActions,
  toolbarActions,
  remote,
  sorting,
}: {
  dataSource: T[];
  loading?: TableProps<T>['loading'];
  pagination?: TableProps<T>['pagination'];
  rowSelection?: TableProps<T>['rowSelection'];
  onSelect?: (post: T) => void;
  renderActions?: (post: T) => ReactNode;
  toolbarActions?: ReactNode;
  remote?: {
    sort: PostCardSort;
    onSortChange: (sort: PostCardSort) => void;
    onPageChange: (page: number, pageSize: number) => void;
    sortOptions?: Array<{ value: PostSort; label: string }>;
  };
  sorting?: {
    sort: PostCardSort;
    onSortChange: (sort: PostCardSort) => void;
    sortOptions?: Array<{ value: PostSort; label: string }>;
  };
}) {
  const selectedRowKeys = rowSelection?.selectedRowKeys ?? [];
  const selectionOnChange = rowSelection?.onChange;
  const [sort, setSort] = useState<PostCardSort>('default');
  const effectiveSort = remote?.sort ?? sorting?.sort ?? sort;
  const sortedDataSource = useMemo(
    () => (remote ? dataSource : sortPostsForCard(dataSource, effectiveSort)),
    [dataSource, effectiveSort, remote],
  );
  const paginationConfig = normalizePostCardPagination(pagination, sortedDataSource.length);
  const initialPagination = paginationConfig && typeof paginationConfig === 'object'
    ? paginationConfig
    : {};
  const [currentPage, setCurrentPage] = useState(
    Number(initialPagination.current ?? initialPagination.defaultCurrent ?? 1),
  );
  const [pageSize, setPageSize] = useState(
    Number(initialPagination.pageSize ?? initialPagination.defaultPageSize ?? 10),
  );
  const effectivePageSize = remote
    ? Number(initialPagination.pageSize ?? initialPagination.defaultPageSize ?? pageSize)
    : pageSize;
  const requestedPage = remote
    ? Number(initialPagination.current ?? initialPagination.defaultCurrent ?? 1)
    : currentPage;
  const totalItems = Math.max(
    Number(initialPagination.total ?? 0),
    sortedDataSource.length,
  );
  const effectiveCurrentPage =
    paginationConfig === false
      ? 1
      : Math.min(requestedPage, Math.max(1, Math.ceil(totalItems / effectivePageSize)));
  const currentPagePosts =
    remote || paginationConfig === false
      ? sortedDataSource
      : sortedDataSource.slice(
          (effectiveCurrentPage - 1) * effectivePageSize,
          effectiveCurrentPage * effectivePageSize,
        );
  const listPagination =
    paginationConfig === false
      ? false
      : {
          ...paginationConfig,
          current: effectiveCurrentPage,
          pageSize: effectivePageSize,
          onChange: (page: number, nextPageSize: number) => {
            setCurrentPage(page);
            setPageSize(nextPageSize);
            remote?.onPageChange(page, nextPageSize);
            paginationConfig?.onChange?.(page, nextPageSize);
          },
        };
  const selectablePosts = currentPagePosts.filter(
    (post) => !rowSelection?.getCheckboxProps?.(post).disabled,
  );
  const selectedKeySet = new Set(selectedRowKeys);
  const selectedSelectableCount = selectablePosts.filter((post) =>
    selectedKeySet.has(post.id),
  ).length;
  const allCurrentSelected =
    selectablePosts.length > 0 && selectedSelectableCount === selectablePosts.length;
  const someCurrentSelected = selectedSelectableCount > 0 && !allCurrentSelected;

  const toggleAllCurrent = () => {
    if (!selectionOnChange) return;
    const nextKeys = new Set(selectedRowKeys);
    for (const post of selectablePosts) {
      if (allCurrentSelected) nextKeys.delete(post.id);
      else nextKeys.add(post.id);
    }
    const nextKeyList = [...nextKeys];
    selectionOnChange(
      nextKeyList,
      sortedDataSource.filter((post) => nextKeys.has(post.id)),
      { type: 'all' },
    );
  };

  return (
    <div className="post-card-view">
      <div className="post-card-toolbar">
        <div className="post-card-toolbar-main">
          {selectionOnChange ? (
            <Checkbox
              checked={allCurrentSelected}
              disabled={selectablePosts.length === 0}
              indeterminate={someCurrentSelected}
              onChange={toggleAllCurrent}
            >
              全选当前页
            </Checkbox>
          ) : null}
          {toolbarActions}
        </div>
        <section className="post-card-control-group" aria-label="卡片排序选项">
          <span className="post-card-control-label">排序</span>
          <Select<PostCardSort>
            aria-label="卡片排序"
            value={effectiveSort}
            onChange={(value) => {
              setCurrentPage(1);
              if (remote) remote.onSortChange(value);
              else if (sorting) sorting.onSortChange(value);
              else setSort(value);
            }}
            options={remote?.sortOptions ?? sorting?.sortOptions ?? POST_SORT_OPTIONS}
          />
        </section>
      </div>
      <List<T>
        className="post-card-grid"
        dataSource={currentPagePosts}
        loading={loading}
        rowKey="id"
        grid={{ gutter: [16, 16], xs: 1, sm: 2, md: 3, lg: 3, xl: 4, xxl: 4 }}
        pagination={listPagination}
        renderItem={(post) => {
          const checkboxProps = rowSelection?.getCheckboxProps?.(post);
          const title = post.title || post.note_id;
          const author = post.author_name || post.external_author_id || '未知作者';
          return (
            <List.Item>
              <Card
                className="post-card"
                size="small"
                hoverable
                cover={
                  onSelect ? (
                    <button
                      type="button"
                      className="post-card-cover-button"
                      aria-label={`查看${title}详情`}
                      onClick={() => onSelect(post)}
                    >
                      <PostCover
                        className="post-card-cover"
                        localSrc={post.media_url}
                        remoteSrc={post.media_remote_url || post.cover_url}
                        alt={`${title}封面`}
                        width="100%"
                        height={236}
                      />
                    </button>
                  ) : (
                    <PostCover
                      className="post-card-cover"
                      localSrc={post.media_url}
                      remoteSrc={post.media_remote_url || post.cover_url}
                      alt={`${title}封面`}
                      width="100%"
                      height={236}
                    />
                  )
                }
                title={
                  <div className="post-card-title-row">
                    {selectionOnChange ? (
                      <Checkbox
                        {...checkboxProps}
                        checked={selectedRowKeys.includes(post.id)}
                        aria-label={`选择${title}`}
                        onChange={() =>
                          toggleSelection(
                            post,
                            selectedRowKeys,
                            sortedDataSource,
                            selectionOnChange,
                          )
                        }
                      />
                    ) : null}
                    {onSelect ? (
                      <Button
                        type="link"
                        className="post-card-title"
                        onClick={() => onSelect(post)}
                      >
                        <Typography.Text ellipsis={{ tooltip: title }}>{title}</Typography.Text>
                      </Button>
                    ) : (
                      <Typography.Text ellipsis={{ tooltip: title }} className="post-card-title">
                        {title}
                      </Typography.Text>
                    )}
                  </div>
                }
              >
                <div className="post-card-meta">
                  <Typography.Text type="secondary" ellipsis={{ tooltip: author }}>
                    {author}
                  </Typography.Text>
                  <Typography.Text type="secondary">
                    {post.note_type === 'video' ? '视频' : '图文'}
                  </Typography.Text>
                </div>
                {post.attention_score != null || post.author_followers_count != null ? (
                  <div className="post-card-meta">
                    <Typography.Text strong>
                      关注分 {post.attention_score == null ? '—' : formatNumber(post.attention_score)}
                    </Typography.Text>
                    <Typography.Text type="secondary">
                      作者粉丝 {formatNumber(post.author_followers_count)}
                    </Typography.Text>
                  </div>
                ) : null}
                <PostCardStats post={post} />
                {renderActions ? (
                  <div className="post-card-actions">{renderActions(post)}</div>
                ) : null}
              </Card>
            </List.Item>
          );
        }}
      />
    </div>
  );
}

export function createPostTableViewRender<T extends PostCardData>(
  view: PostViewMode,
  onSelect: (post: T) => void,
  renderActions?: (post: T) => ReactNode,
  rowSelection?: TableProps<T>['rowSelection'],
  toolbarActions?: ReactNode,
  remote?: {
    sort: PostCardSort;
    onSortChange: (sort: PostCardSort) => void;
    onPageChange: (page: number, pageSize: number) => void;
    sortOptions?: Array<{ value: PostSort; label: string }>;
  },
  sorting?: {
    sort: PostCardSort;
    onSortChange: (sort: PostCardSort) => void;
    sortOptions?: Array<{ value: PostSort; label: string }>;
  },
) {
  return (tableProps: TableProps<T>, defaultDom: ReactNode) => {
    if (view === 'list') return defaultDom;
    return (
      <PostCardGrid
        dataSource={Array.from(tableProps.dataSource ?? [])}
        loading={tableProps.loading}
        pagination={tableProps.pagination}
        rowSelection={rowSelection ?? tableProps.rowSelection}
        onSelect={onSelect}
        renderActions={renderActions}
        toolbarActions={toolbarActions}
        remote={remote}
        sorting={sorting}
      />
    );
  };
}
