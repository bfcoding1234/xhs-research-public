import { LinkOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ProColumns } from '@ant-design/pro-components';
import { PageContainer, ProTable } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { history, Link } from '@umijs/max';
import { Alert, Button, Space, Tag, Typography } from 'antd';
import { useDeferredValue, useMemo, useState } from 'react';
import TaskCreatedModal from '@/components/TaskCreatedModal';
import PostCover from '@/features/posts/PostCover';
import PostCommentCollectionAction from '@/features/posts/PostCommentCollectionAction';
import PostListFilters, {
  DEFAULT_POST_LIST_FILTERS,
  PostDetailStatus,
  PostOcrStatus,
  PostVisionStatus,
} from '@/features/posts/PostListFilters';
import PostOriginalLink from '@/features/posts/PostOriginalLink';
import PostDetailUpdateControl from '@/features/posts/PostDetailUpdateControl';
import {
  createPostTableViewRender,
  DEFAULT_POST_VIEW_MODE,
  GLOBAL_POST_SORT_OPTIONS,
  postSortFromTable,
  postSortOrder,
  PostListHeader,
  PostToolbarActions,
  type PostCardSort,
  type PostViewMode,
} from '@/features/posts/PostView';
import {
  POST_PAGE_SIZE_OPTIONS,
  usePostPageSize,
} from '@/features/posts/postListPreferences';
import { useListSort } from '@/features/preferences/listSortPreferences';
import { TABLE_COLUMN_PREFERENCES } from '@/features/preferences/tableColumnPreferences';
import AddToProjectModal from '@/features/references/AddToProjectModal';
import { createPersistentRowSelection } from '@/features/selection/persistentRowSelection';
import { apiService } from '@/services/api';
import { queryKeys } from '@/services/queryKeys';
import type { Post, PostQuery, TaskReceipt } from '@/types';
import { formatDate, formatNumber, formatPublishDate } from '@/utils/format';
import { buildPostDetailPath } from '@/utils/postNavigation';

const GLOBAL_POST_SORT_VALUES = GLOBAL_POST_SORT_OPTIONS.map(({ value }) => value);

export default function PostsPage() {
  const [filters, setFilters] = useState(DEFAULT_POST_LIST_FILTERS);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [linkingIds, setLinkingIds] = useState<number[]>([]);
  const [view, setView] = useState<PostViewMode>(DEFAULT_POST_VIEW_MODE);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = usePostPageSize();
  const [sort, setSort] = useListSort<PostCardSort>(
    'posts.global',
    GLOBAL_POST_SORT_VALUES,
    'default',
  );
  const [createdTask, setCreatedTask] = useState<TaskReceipt | null>(null);
  const deferredFilters = useDeferredValue(filters);
  const postQuery = useMemo<PostQuery>(() => ({
    page,
    page_size: pageSize,
    ...deferredFilters,
    sort,
  }), [deferredFilters, page, pageSize, sort]);
  const posts = useQuery({
    queryKey: [...queryKeys.posts, postQuery],
    queryFn: ({ signal }) => apiService.posts(postQuery, signal),
    placeholderData: (previous) => previous,
  });
  const settings = useQuery({
    queryKey: queryKeys.settings,
    queryFn: ({ signal }) => apiService.settings(signal),
  });

  const data = posts.data?.items ?? [];
  const total = posts.data?.total ?? 0;
  const rowSelection = createPersistentRowSelection<Post>(selectedIds, setSelectedIds);

  const columns: ProColumns<Post>[] = [
    {
      title: '封面',
      dataIndex: 'media_url',
      width: 72,
      fixed: 'left',
      render: (_, row) => (
        <PostCover
          localSrc={row.media_url}
          remoteSrc={row.media_remote_url || row.cover_url}
          alt={row.title || '帖子封面'}
          preview
        />
      ),
    },
    {
      title: '帖子',
      dataIndex: 'title',
      width: 280,
      fixed: 'left',
      render: (_, row) => (
        <Space orientation="vertical" size={0}>
          <Link to={buildPostDetailPath(row.id, { source: 'global' })}>
            {row.title || row.note_id}
          </Link>
          <Typography.Text type="secondary" className="mono">
            {row.note_id}
          </Typography.Text>
        </Space>
      ),
      key: 'title',
      sorter: true,
      sortDirections: ['ascend', 'descend'],
      sortOrder: postSortOrder(sort, 'title'),
    },
    {
      title: '作者',
      dataIndex: 'author_name',
      width: 280,
      render: (_, row) =>
        row.author_id ? (
          <Link to={`/authors/${row.author_id}`}>{row.author_name || row.external_author_id}</Link>
        ) : (
          row.author_name || '未知作者'
        ),
    },
    {
      title: '类型',
      dataIndex: 'note_type',
      width: 90,
      render: (_, row) => <Tag>{row.note_type === 'video' ? '视频' : '图文'}</Tag>,
    },
    {
      title: '信息完整度',
      dataIndex: 'detail_level',
      width: 130,
      render: (_, row) => <PostDetailStatus value={row.detail_level} />,
    },
    {
      title: '是否已有 OCR 识图',
      dataIndex: 'has_ocr_result',
      width: 150,
      render: (_, row) => <PostOcrStatus value={row.has_ocr_result} status={row.ocr_status} />,
    },
    {
      title: '是否已有图片理解',
      dataIndex: 'has_vision_result',
      width: 140,
      render: (_, row) => <PostVisionStatus value={row.has_vision_result} />,
    },
    {
      title: '点赞',
      dataIndex: 'likes_count',
      width: 110,
      align: 'right',
      renderText: formatNumber,
      key: 'likes',
      sorter: true,
      sortDirections: ['descend', 'ascend'],
      sortOrder: postSortOrder(sort, 'likes'),
    },
    {
      title: '收藏',
      dataIndex: 'favorites_count',
      width: 110,
      align: 'right',
      renderText: formatNumber,
      key: 'favorites',
      sorter: true,
      sortDirections: ['descend', 'ascend'],
      sortOrder: postSortOrder(sort, 'favorites'),
    },
    {
      title: '评论',
      dataIndex: 'comments_count',
      width: 110,
      align: 'right',
      renderText: formatNumber,
      key: 'comments',
      sorter: true,
      sortDirections: ['descend', 'ascend'],
      sortOrder: postSortOrder(sort, 'comments'),
    },
    {
      title: '发布时间',
      dataIndex: 'publish_date',
      width: 150,
      renderText: (value: string) => formatPublishDate(value),
      key: 'published',
      sorter: true,
      sortDirections: ['descend', 'ascend'],
      sortOrder: postSortOrder(sort, 'published'),
    },
    {
      title: '关联项目',
      dataIndex: 'project_count',
      width: 110,
      align: 'right',
      render: (_, row) => `${formatNumber(row.project_count ?? 0)} 个`,
      key: 'project_count',
      sorter: true,
      sortDirections: ['descend', 'ascend'],
      sortOrder: postSortOrder(sort, 'project_count'),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 180,
      renderText: (value: string) => formatDate(value),
      key: 'updated',
      sorter: true,
      sortDirections: ['descend', 'ascend'],
      sortOrder: postSortOrder(sort, 'updated'),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 180,
      fixed: 'right',
      render: (_, row) => [
        <PostOriginalLink key="original" noteUrl={row.note_url} />,
        <PostCommentCollectionAction key="comments" post={row} />,
        <Button
          key="link"
          type="link"
          icon={<LinkOutlined />}
          onClick={() => setLinkingIds([row.id])}
        >
          关联
        </Button>,
      ],
    },
  ];
  const batchActions = (
    <PostToolbarActions
      selectedCount={selectedIds.length}
      onClearSelection={() => setSelectedIds([])}
    >
      <PostDetailUpdateControl
        posts={data}
        selectedIds={selectedIds}
        scope="global"
        delaySettings={settings.data}
        onSelectionChange={setSelectedIds}
        onCreated={setCreatedTask}
      />
      <Button
        type="primary"
        icon={<LinkOutlined />}
        aria-label={selectedIds.length ? `关联到项目，已选 ${selectedIds.length} 篇` : '关联到项目'}
        disabled={selectedIds.length === 0}
        onClick={() => setLinkingIds(selectedIds)}
      >
        关联到项目
      </Button>
    </PostToolbarActions>
  );
  const renderPostActions = (post: Post) => (
    <Space size={8}>
      <PostOriginalLink noteUrl={post.note_url} />
      <PostCommentCollectionAction post={post} />
      <Button
        type="link"
        icon={<LinkOutlined />}
        onClick={() => setLinkingIds([post.id])}
      >
        关联
      </Button>
    </Space>
  );

  return (
    <PageContainer
      title="帖子"
      subTitle="全局帖子主数据；项目仅保存对这些帖子的引用"
      extra={[
        <Button
          key="refresh"
          icon={<ReloadOutlined />}
          loading={posts.isFetching}
          onClick={() => posts.refetch()}
        >
          刷新
        </Button>,
      ]}
    >
      {posts.isError ? (
        <Alert
          showIcon
          type="error"
          title="帖子列表加载失败"
          description={posts.error.message}
          action={<Button onClick={() => posts.refetch()}>重试</Button>}
        />
      ) : null}
      <PostListHeader
        title={`全部帖子（${total}）`}
        view={view}
        onViewChange={setView}
        showViewLabel
        query={(
          <PostListFilters
            value={filters}
            onChange={(next) => {
              setFilters(next);
              setPage(1);
            }}
          />
        )}
      />
      <ProTable<Post>
        className="post-list-table"
        rowKey="id"
        headerTitle={view === 'list' ? batchActions : false}
        loading={posts.isPending}
        columns={columns}
        dataSource={data}
        search={false}
        tableViewRender={createPostTableViewRender(
          view,
          (post) => history.push(buildPostDetailPath(post.id, { source: 'global' })),
          renderPostActions,
          rowSelection,
          batchActions,
          {
            sort,
            onSortChange: (next) => {
              setSort(next);
              setPage(1);
            },
            onPageChange: (nextPage, nextPageSize) => {
              setPage(nextPage);
              setPageSize(nextPageSize);
            },
            sortOptions: GLOBAL_POST_SORT_OPTIONS,
          },
        )}
        onChange={(_, __, sorter, extra) => {
          if (extra.action !== 'sort' || Array.isArray(sorter)) return;
          setSort(postSortFromTable(sorter.columnKey ?? sorter.field, sorter.order));
          setPage(1);
        }}
        scroll={{ x: 1830 }}
        pagination={{
          current: posts.data?.page ?? page,
          pageSize: posts.data?.page_size ?? pageSize,
          total,
          onChange: (nextPage, nextPageSize) => {
            setPage(nextPage);
            setPageSize(nextPageSize);
          },
          showSizeChanger: true,
          pageSizeOptions: POST_PAGE_SIZE_OPTIONS.map(String),
          showTotal: (total) => `共 ${total} 篇`,
        }}
        options={view === 'list'
          ? { reload: false, density: true, setting: true, fullScreen: true }
          : false}
        columnsState={TABLE_COLUMN_PREFERENCES.globalPosts}
        rowSelection={rowSelection}
        tableAlertRender={false}
        toolBarRender={view === 'list' ? () => [] : false}
      />
      <AddToProjectModal
        open={linkingIds.length > 0}
        entityType="post"
        entityIds={linkingIds}
        onClose={() => setLinkingIds([])}
        onSuccess={() => setSelectedIds([])}
      />
      <TaskCreatedModal
        task={createdTask}
        onStay={() => setCreatedTask(null)}
        onView={(task) => {
          setCreatedTask(null);
          history.push(`/tasks/${task.id}`);
        }}
      />
    </PageContainer>
  );
}
