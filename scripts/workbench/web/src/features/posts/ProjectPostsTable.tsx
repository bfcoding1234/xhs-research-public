import {
  DeleteOutlined,
  FileSearchOutlined,
  InfoCircleOutlined,
  LinkOutlined,
} from '@ant-design/icons';
import type { ProColumns } from '@ant-design/pro-components';
import { ProTable } from '@ant-design/pro-components';
import { Button, Popover, Space, Tag, Typography } from 'antd';
import { useState } from 'react';
import { TABLE_COLUMN_PREFERENCES } from '@/features/preferences/tableColumnPreferences';
import type {
  AppSettings,
  Post,
  ProjectPostCoverage,
  ProjectPostQuery,
  TaskReceipt,
} from '@/types';
import { createPersistentRowSelection } from '@/features/selection/persistentRowSelection';
import { formatDate, formatNumber, formatPublishDate } from '@/utils/format';
import PostCover from './PostCover';
import PostCommentCollectionAction from './PostCommentCollectionAction';
import PostListFilters, {
  PostDetailStatus,
  PostOcrStatus,
  PostVisionStatus,
} from './PostListFilters';
import PostOriginalLink from './PostOriginalLink';
import PostDetailUpdateControl from './PostDetailUpdateControl';
import {
  createPostTableViewRender,
  DEFAULT_POST_VIEW_MODE,
  postSortFromTable,
  postSortOrder,
  PostListHeader,
  PostToolbarActions,
  PROJECT_POST_SORT_OPTIONS,
  type PostViewMode,
  type PostCardSort,
} from './PostView';
import { POST_PAGE_SIZE_OPTIONS } from './postListPreferences';

const DEFAULT_TABLE_QUERY: ProjectPostQuery = {
  page: 1,
  page_size: 20,
  query: '',
  type: 'all',
  detail: 'all',
  ocr: 'all',
  vision: 'all',
  media_storage: 'all',
  popularity: 'all',
  sort: 'default',
};

function CoverageInfoPopover({
  title,
  coverage,
  onShowPending,
  onStartOcr,
}: {
  title: '信息完整度' | 'OCR';
  coverage?: ProjectPostCoverage;
  onShowPending: () => void;
  onStartOcr?: () => void;
}) {
  if (!coverage) return title;
  const isOcr = title === 'OCR';
  const completed = isOcr ? coverage.ocr_completed : coverage.detailed;
  const total = isOcr ? coverage.ocr_available : coverage.total;
  const pending = isOcr ? coverage.ocr_pending : coverage.preview;
  return (
    <Space size={4}>
      <span>{title}</span>
      <Popover
        title={`${title}处理进度`}
        trigger="click"
        content={(
          <Space orientation="vertical" size={4}>
            <Typography.Text>已完成 {completed} / {total}</Typography.Text>
            <Typography.Text type="secondary">
              {isOcr
                ? `待处理 ${pending} 篇 · 无可处理图片 ${coverage.ocr_other} 篇`
                : `待补全 ${pending} 篇`}
            </Typography.Text>
            <Space size={8}>
              <Button type="link" size="small" onClick={onShowPending} disabled={!pending}>
                {isOcr ? '查看待 OCR' : '查看待补全'}
              </Button>
              {isOcr ? (
                <Button type="link" size="small" onClick={onStartOcr} disabled={!pending}>
                  去处理
                </Button>
              ) : null}
            </Space>
          </Space>
        )}
      >
        <Button
          aria-label={`查看${title}处理进度`}
          className="post-coverage-info-trigger"
          icon={<InfoCircleOutlined />}
          size="small"
          type="text"
        />
      </Popover>
    </Space>
  );
}

export default function ProjectPostsTable({
  posts,
  total = posts.length,
  projectTotal = total,
  page = 1,
  pageSize = 20,
  loading = false,
  query = DEFAULT_TABLE_QUERY,
  onQueryChange = () => undefined,
  onPageChange = () => undefined,
  onOpen,
  onLink,
  onUnlink,
  onVision,
  projectId,
  detailTtlDays,
  delaySettings,
  onTaskCreated,
  visionDisabled = false,
  visionDisabledReason,
  coverage,
}: {
  posts: Post[];
  total?: number;
  projectTotal?: number;
  page?: number;
  pageSize?: number;
  loading?: boolean;
  query?: ProjectPostQuery;
  onQueryChange?: (next: Partial<ProjectPostQuery>) => void;
  onPageChange?: (page: number, pageSize: number) => void;
  onOpen: (post: Post) => void;
  onLink: () => void;
  onUnlink: (ids: number[]) => unknown;
  onVision: () => void;
  projectId: number;
  detailTtlDays?: number;
  delaySettings?: Pick<
    AppSettings,
    | 'post_delay_min_seconds'
    | 'post_delay_max_seconds'
    | 'batch_delay_min_seconds'
    | 'batch_delay_max_seconds'
  >;
  onTaskCreated: (task: TaskReceipt) => void | Promise<void>;
  visionDisabled?: boolean;
  visionDisabledReason?: string;
  coverage?: ProjectPostCoverage;
}) {
  const [view, setView] = useState<PostViewMode>(DEFAULT_POST_VIEW_MODE);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const rowSelection = createPersistentRowSelection<Post>(selectedIds, setSelectedIds);
  const columns: ProColumns<Post>[] = [
    {
      title: '封面',
      dataIndex: 'media_url',
      width: 72,
      fixed: 'left',
      search: false,
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
          <Button
            type="link"
            style={{ height: 'auto', padding: 0, textAlign: 'left', whiteSpace: 'normal' }}
            onClick={() => onOpen(row)}
          >
            {row.title || row.note_id}
          </Button>
          <Typography.Text type="secondary">{row.author_name || '未知作者'}</Typography.Text>
        </Space>
      ),
      key: 'title',
      sorter: true,
      sortDirections: ['ascend', 'descend'],
      sortOrder: postSortOrder(query.sort, 'title'),
    },
    {
      title: '关注分',
      tooltip: '项目内相对分数：以互动/粉丝为主体，并平滑极小粉丝数和低互动样本',
      dataIndex: 'attention_score',
      width: 104,
      align: 'right',
      renderText: (value: number | null) => value == null ? '—' : formatNumber(value),
      key: 'attention',
      sorter: true,
      sortDirections: ['descend', 'ascend'],
      sortOrder: postSortOrder(query.sort, 'attention'),
    },
    {
      title: '作者粉丝',
      dataIndex: 'author_followers_count',
      width: 116,
      align: 'right',
      renderText: (value: number | null) => value == null ? '—' : formatNumber(value),
      key: 'author_followers',
    },
    {
      title: '类型',
      dataIndex: 'note_type',
      width: 190,
      render: (_, row) => <Tag>{row.note_type === 'video' ? '视频' : '图文'}</Tag>,
    },
    {
      title: (
        <CoverageInfoPopover
          title="信息完整度"
          coverage={coverage}
          onShowPending={() => showCoverageFilter({ detail: 'preview' })}
        />
      ),
      dataIndex: 'detail_level',
      width: 130,
      render: (_, row) => <PostDetailStatus value={row.detail_level} />,
    },
    {
      title: (
        <CoverageInfoPopover
          title="OCR"
          coverage={coverage}
          onShowPending={() => showCoverageFilter({ ocr: 'pending' })}
          onStartOcr={onVision}
        />
      ),
      dataIndex: 'has_ocr_result',
      width: 100,
      render: (_, row) => <PostOcrStatus value={row.has_ocr_result} status={row.ocr_status} />,
    },
    {
      title: '图片理解',
      tooltip: '是否已有图片理解',
      dataIndex: 'has_vision_result',
      width: 116,
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
      sortOrder: postSortOrder(query.sort, 'likes'),
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
      sortOrder: postSortOrder(query.sort, 'favorites'),
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
      sortOrder: postSortOrder(query.sort, 'comments'),
    },
    {
      title: '发布时间',
      dataIndex: 'publish_date',
      width: 150,
      renderText: (value: string) => formatPublishDate(value),
      key: 'published',
      sorter: true,
      sortDirections: ['descend', 'ascend'],
      sortOrder: postSortOrder(query.sort, 'published'),
    },
    {
      title: '热度',
      dataIndex: 'popularity_level',
      width: 100,
      render: (_, row) =>
        row.popularity_level ? <Tag color="blue">{row.popularity_level}</Tag> : '—',
      key: 'popularity',
      sorter: true,
      sortDirections: ['descend', 'ascend'],
      sortOrder: postSortOrder(query.sort, 'popularity'),
    },
    {
      title: '来源',
      dataIndex: 'sources',
      ellipsis: true,
      width: 160,
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 180,
      renderText: (value: string) => formatDate(value),
      key: 'updated',
      sorter: true,
      sortDirections: ['descend', 'ascend'],
      sortOrder: postSortOrder(query.sort, 'updated'),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 90,
      fixed: 'right',
      render: (_, row) => [
        <PostOriginalLink key="original" noteUrl={row.note_url} />,
        <PostCommentCollectionAction key="comments" post={row} />,
      ],
    },
  ];
  const queryControls = (
    <PostListFilters
      value={{
        query: query.query,
        type: query.type,
        detail: query.detail,
        ocr: query.ocr,
        vision: query.vision,
      }}
      onChange={(filters) => onQueryChange({ ...filters, page: 1 })}
      additionalFilters={[
        {
          key: 'media_storage',
          label: '媒体存储状态',
          ariaLabel: '按媒体存储状态筛选',
          value: query.media_storage,
          options: [
            { value: 'all', label: '全部媒体状态' },
            { value: 'remote', label: '远程图片待下载' },
            { value: 'local', label: '正文图片已本地化' },
            { value: 'none', label: '无正文图片' },
          ],
          onChange: (media_storage) =>
            onQueryChange({
              media_storage: media_storage as ProjectPostQuery['media_storage'],
              page: 1,
            }),
        },
        {
          key: 'popularity',
          label: '帖子热度',
          ariaLabel: '按帖子热度筛选',
          value: query.popularity,
          options: [
            { value: 'all', label: '全部热度' },
            ...['高热', '较热', '一般', '低表现'].map((item) => ({ value: item, label: item })),
          ],
          onChange: (popularity) =>
            onQueryChange({ popularity: popularity as ProjectPostQuery['popularity'], page: 1 }),
        },
      ]}
    />
  );
  const postActions = (
    <PostToolbarActions
      selectedCount={selectedIds.length}
      onClearSelection={() => setSelectedIds([])}
    >
      <PostDetailUpdateControl
        posts={posts}
        selectedIds={selectedIds}
        scope="project"
        scopeId={projectId}
        detailTtlDays={detailTtlDays}
        delaySettings={delaySettings}
        onSelectionChange={setSelectedIds}
        onCreated={onTaskCreated}
      />
      <Button key="link" icon={<LinkOutlined />} onClick={onLink}>
        关联帖子
      </Button>
      <Button
        key="unlink"
        danger
        icon={<DeleteOutlined />}
        disabled={selectedIds.length === 0}
        aria-label={selectedIds.length ? `取消关联，已选 ${selectedIds.length} 篇` : '取消关联'}
        onClick={() => {
          void Promise.resolve(onUnlink(selectedIds))
            .then(() => setSelectedIds([]))
            .catch(() => undefined);
        }}
      >
        取消关联
      </Button>
      <Button
        key="vision"
        icon={<FileSearchOutlined />}
        onClick={onVision}
        disabled={visionDisabled}
        title={visionDisabledReason}
      >
        补充图片理解
      </Button>
    </PostToolbarActions>
  );
  const renderPostActions = (post: Post) => (
    <Space size={8}>
      <PostOriginalLink noteUrl={post.note_url} />
      <PostCommentCollectionAction post={post} />
    </Space>
  );
  function showCoverageFilter(filters: Partial<Pick<ProjectPostQuery, 'detail' | 'ocr'>>) {
    onQueryChange({
      query: '',
      type: 'all',
      detail: filters.detail ?? 'all',
      ocr: filters.ocr ?? 'all',
      vision: 'all',
      media_storage: 'all',
      popularity: 'all',
      page: 1,
    });
  }
  return (
    <>
      <PostListHeader
        title={`帖子（${total}/${projectTotal}）`}
        view={view}
        onViewChange={setView}
        query={queryControls}
        showViewLabel
      />
      <ProTable<Post>
        className="post-list-table"
        rowKey="id"
        headerTitle={view === 'list' ? postActions : false}
        columns={columns}
        dataSource={posts}
        loading={loading}
        search={false}
        tableViewRender={createPostTableViewRender(
          view,
          onOpen,
          renderPostActions,
          rowSelection,
          postActions,
          {
            sort: query.sort as PostCardSort,
            onSortChange: (sort) => onQueryChange({ sort, page: 1 }),
            onPageChange,
            sortOptions: PROJECT_POST_SORT_OPTIONS,
          },
        )}
        onChange={(_, __, sorter, extra) => {
          if (extra.action !== 'sort' || Array.isArray(sorter)) return;
          onQueryChange({
            sort: postSortFromTable(sorter.columnKey ?? sorter.field, sorter.order),
            page: 1,
          });
        }}
        scroll={{ x: 1150 }}
        pagination={{
          current: page,
          pageSize,
          total,
          onChange: onPageChange,
          showSizeChanger: true,
          pageSizeOptions: POST_PAGE_SIZE_OPTIONS.map(String),
          showTotal: (total) => `共 ${total} 篇`,
        }}
        options={view === 'list'
          ? { reload: false, density: true, setting: true, fullScreen: true }
          : false}
        columnsState={{
          ...TABLE_COLUMN_PREFERENCES.projectPosts,
          defaultValue: {
            likes: { show: false },
            favorites: { show: false },
            comments: { show: false },
            published: { show: false },
            popularity: { show: false },
            sources: { show: false },
            updated: { show: false },
          },
        }}
        rowSelection={rowSelection}
        tableAlertRender={false}
        toolBarRender={view === 'list' ? () => [] : false}
      />
    </>
  );
}
