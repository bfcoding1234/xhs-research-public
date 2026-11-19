import {
  ExportOutlined,
  FileSearchOutlined,
  IdcardOutlined,
  LinkOutlined,
  QuestionCircleOutlined,
  SyncOutlined,
  UserOutlined,
} from '@ant-design/icons';
import type { ProColumns } from '@ant-design/pro-components';
import { PageContainer, ProTable } from '@ant-design/pro-components';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { history, Link, useLocation, useParams } from '@umijs/max';
import {
  App,
  Avatar,
  Button,
  Card,
  Descriptions,
  Popover,
  Result,
  Space,
  Statistic,
  Tabs,
  Tag,
  Typography,
} from 'antd';
import { useEffect, useState } from 'react';
import { QueryError, QueryLoading } from '@/components/QueryState';
import TaskCreatedModal from '@/components/TaskCreatedModal';
import PostCover from '@/features/posts/PostCover';
import PostCommentCollectionAction from '@/features/posts/PostCommentCollectionAction';
import PostListFilters, {
  DEFAULT_POST_LIST_FILTERS,
  filterPostList,
  filterPostsByMediaStorage,
  PostDetailStatus,
  PostOcrStatus,
  PostVisionStatus,
} from '@/features/posts/PostListFilters';
import PostOriginalLink from '@/features/posts/PostOriginalLink';
import PostDetailUpdateControl from '@/features/posts/PostDetailUpdateControl';
import { TABLE_COLUMN_PREFERENCES } from '@/features/preferences/tableColumnPreferences';
import { createPersistentRowSelection } from '@/features/selection/persistentRowSelection';
import {
  createPostTableViewRender,
  POST_SORT_OPTIONS,
  postSortFromTable,
  postSortOrder,
  PostListHeader,
  PostToolbarActions,
  sortPostsForCard,
  type PostCardSort,
  type PostViewMode,
} from '@/features/posts/PostView';
import {
  POST_PAGE_SIZE_OPTIONS,
  usePostPageSize,
} from '@/features/posts/postListPreferences';
import { useListSort } from '@/features/preferences/listSortPreferences';
import AddToProjectModal from '@/features/references/AddToProjectModal';
import AuthorUpdateModal, {
  buildAuthorBasicInfoUpdateConfiguration,
} from '@/features/authors/AuthorUpdateModal';
import ReportPanel from '@/features/reports/ReportPanel';
import ReportRunModal from '@/features/reports/ReportRunModal';
import VisionRunModal from '@/features/vision/VisionRunModal';
import { apiService } from '@/services/api';
import { queryKeys } from '@/services/queryKeys';
import type { Author, AuthorPost, MediaStorageFilter, TaskReceipt } from '@/types';
import {
  authorPostCollectionStats,
  formatAuthorPostCoverage,
  formatAuthorPostCollectionStats,
  storedAuthorPostCount,
} from '@/utils/authors';
import { formatDate, formatNumber, formatPublishDate } from '@/utils/format';
import { buildPostDetailPath } from '@/utils/postNavigation';
import './index.css';

export interface AuthorDetailPageProps {
  authorId?: number;
  embedded?: boolean;
  routeBase?: string;
  showBack?: boolean;
  showBasicInfoUpdate?: boolean;
  showProjectAssociation?: boolean;
  subTitle?: string;
}

const AUTHOR_POST_SORT_VALUES = POST_SORT_OPTIONS.map(({ value }) => value);

export default function AuthorDetailPage({
  authorId,
  embedded = false,
  routeBase,
  showBack = authorId === undefined,
  showBasicInfoUpdate = true,
  showProjectAssociation = true,
  subTitle = '作者详情',
}: AuthorDetailPageProps = {}) {
  const params = useParams<{ id?: string; tab?: string }>();
  const { pathname } = useLocation();
  const id = authorId ?? Number(params.id);
  const detailBase = routeBase ?? `/authors/${id}`;
  const postDetailBase = pathname.startsWith('/my-projects') ? 'my-projects' : 'authors';
  const routeTab = params.tab === 'reports' ? 'reports' : 'posts';
  const [embeddedTab, setEmbeddedTab] = useState<'posts' | 'reports'>('posts');
  const tab = embedded ? embeddedTab : routeTab;
  const [linking, setLinking] = useState(false);
  const [updatingBasicInfo, setUpdatingBasicInfo] = useState(false);
  const [updating, setUpdating] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  const [visionOpen, setVisionOpen] = useState(false);
  const [createdTask, setCreatedTask] = useState<TaskReceipt | null>(null);
  const [postFilters, setPostFilters] = useState(DEFAULT_POST_LIST_FILTERS);
  const [postMediaStorage, setPostMediaStorage] = useState<MediaStorageFilter>('all');
  const [selectedPostIds, setSelectedPostIds] = useState<number[]>([]);
  const [linkingPostIds, setLinkingPostIds] = useState<number[]>([]);
  const [view, setView] = useState<PostViewMode>('list');
  const [postSort, setPostSort] = useListSort<PostCardSort>(
    'posts.author',
    AUTHOR_POST_SORT_VALUES,
    'default',
  );
  const [postPageSize, setPostPageSize] = usePostPageSize();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const handleTaskCreated = (task: TaskReceipt) => {
    setCreatedTask(task);
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.authorReports(id), exact: true }),
      queryClient.invalidateQueries({ queryKey: queryKeys.authorVision(id), exact: true }),
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks, exact: true }),
      queryClient.invalidateQueries({ queryKey: queryKeys.task(task.id), exact: true }),
    ]);
  };
  const updateBasicInfo = async (targetAuthor: Author) => {
    setUpdatingBasicInfo(true);
    try {
      const task = await apiService.createTask(
        undefined,
        'author',
        buildAuthorBasicInfoUpdateConfiguration(targetAuthor),
      );
      handleTaskCreated(task);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '基础信息更新任务发起失败');
    } finally {
      setUpdatingBasicInfo(false);
    }
  };
  const author = useQuery({
    queryKey: queryKeys.author(id),
    queryFn: ({ signal }) => apiService.author(id, signal),
    enabled: Number.isInteger(id) && id > 0,
  });
  const settings = useQuery({
    queryKey: queryKeys.settings,
    queryFn: ({ signal }) => apiService.settings(signal),
  });
  const reports = useQuery({
    queryKey: queryKeys.authorReports(id),
    queryFn: ({ signal }) => apiService.authorReports(id, signal),
    enabled: Number.isInteger(id) && id > 0,
    refetchInterval: (query) =>
      query.state.data?.some((report) => report.status === 'generating') ? 2_000 : false,
  });
  const visionStatus = useQuery({
    queryKey: queryKeys.authorVision(id),
    queryFn: ({ signal }) => apiService.authorVisionStatus(id, signal),
    enabled: Number.isInteger(id) && id > 0 && tab === 'posts',
  });
  const reportStatus = useQuery({
    queryKey: queryKeys.authorReportStatus(id),
    queryFn: ({ signal }) => apiService.authorReportStatus(id, signal),
    enabled: Number.isInteger(id) && id > 0 && tab === 'reports',
  });
  const generateDataSummary = useMutation({
    mutationFn: () => apiService.generateAuthorDataSummary(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.authorReports(id), exact: true });
      message.success('数据摘要已生成');
    },
    onError: (error) => message.error(error.message),
  });
  useEffect(() => {
    setSelectedPostIds([]);
    setLinkingPostIds([]);
    setEmbeddedTab('posts');
  }, [id]);

  if (!Number.isInteger(id) || id <= 0) {
    return (
      <Result
        status="404"
        title="作者不存在"
        extra={<Button onClick={() => history.push('/authors')}>返回作者列表</Button>}
      />
    );
  }
  if (author.isPending) {
    const loading = <QueryLoading rows={8} />;
    return embedded ? loading : <PageContainer>{loading}</PageContainer>;
  }
  if (author.isError) {
    const error = <QueryError error={author.error} retry={() => author.refetch()} />;
    if (embedded) return error;
    return <PageContainer>{error}</PageContainer>;
  }

  const value = author.data;
  const storedPostCount = storedAuthorPostCount(value);
  const collectionStats = authorPostCollectionStats(value);
  const filteredPosts = sortPostsForCard(
    filterPostsByMediaStorage(
      filterPostList(value.posts ?? [], postFilters),
      postMediaStorage,
    ),
    postSort,
  );
  const columns: ProColumns<AuthorPost>[] = [
    {
      title: '封面',
      dataIndex: 'media_url',
      width: 72,
      fixed: 'left',
      render: (_, post) => (
        <PostCover
          localSrc={post.media_url}
          remoteSrc={post.media_remote_url || post.cover_url}
          alt={post.title || '帖子封面'}
          preview
        />
      ),
    },
    {
      title: '帖子',
      dataIndex: 'title',
      width: 280,
      fixed: 'left',
      render: (_, post) => (
        <Space orientation="vertical" size={0}>
          <Link
            to={buildPostDetailPath(post.id, {
              source: 'author',
              authorId: id,
              base: postDetailBase,
            })}
          >
            {post.title || post.note_id}
          </Link>
          <Typography.Text type="secondary" className="mono">
            {post.note_id}
          </Typography.Text>
        </Space>
      ),
      key: 'title',
      sorter: true,
      sortDirections: ['ascend', 'descend'],
      sortOrder: postSortOrder(postSort, 'title'),
    },
    {
      title: '类型',
      dataIndex: 'note_type',
      width: 90,
      render: (_, post) => <Tag>{post.note_type === 'video' ? '视频' : '图文'}</Tag>,
    },
    {
      title: '信息完整度',
      dataIndex: 'detail_level',
      width: 130,
      render: (_, post) => <PostDetailStatus value={post.detail_level} />,
    },
    {
      title: '是否已有 OCR 识图',
      dataIndex: 'has_ocr_result',
      width: 150,
      render: (_, post) => <PostOcrStatus value={post.has_ocr_result} status={post.ocr_status} />,
    },
    {
      title: '是否已有图片理解',
      dataIndex: 'has_vision_result',
      width: 140,
      render: (_, post) => <PostVisionStatus value={post.has_vision_result} />,
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
      sortOrder: postSortOrder(postSort, 'likes'),
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
      sortOrder: postSortOrder(postSort, 'favorites'),
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
      sortOrder: postSortOrder(postSort, 'comments'),
    },
    {
      title: '发布时间',
      dataIndex: 'publish_date',
      width: 150,
      renderText: (date: string) => formatPublishDate(date),
      key: 'published',
      sorter: true,
      sortDirections: ['descend', 'ascend'],
      sortOrder: postSortOrder(postSort, 'published'),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 280,
      renderText: (date: string) => formatDate(date),
      key: 'updated',
      sorter: true,
      sortDirections: ['descend', 'ascend'],
      sortOrder: postSortOrder(postSort, 'updated'),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 180,
      fixed: 'right',
      render: (_, post) => [
        <PostOriginalLink key="original" noteUrl={post.note_url} />,
        <PostCommentCollectionAction key="comments" post={post} />,
        <Button
          key="link"
          type="link"
          icon={<LinkOutlined />}
          onClick={() => setLinkingPostIds([post.id])}
        >
          关联
        </Button>,
      ],
    },
  ];
  const postRowSelection = createPersistentRowSelection<AuthorPost>(
    selectedPostIds,
    setSelectedPostIds,
  );
  const postBatchActions = (
    <PostToolbarActions
      selectedCount={selectedPostIds.length}
      onClearSelection={() => setSelectedPostIds([])}
    >
      <PostDetailUpdateControl
        posts={value.posts ?? []}
        selectedIds={selectedPostIds}
        scope="author"
        scopeId={id}
        detailTtlDays={settings.data?.detail_ttl_days}
        delaySettings={settings.data}
        onSelectionChange={setSelectedPostIds}
        onCreated={handleTaskCreated}
      />
      <Button
        type="primary"
        icon={<LinkOutlined />}
        aria-label={
          selectedPostIds.length ? `关联到项目，已选 ${selectedPostIds.length} 篇` : '关联到项目'
        }
        disabled={selectedPostIds.length === 0}
        onClick={() => setLinkingPostIds(selectedPostIds)}
      >
        关联到项目
      </Button>
      <Button
        icon={<FileSearchOutlined />}
        onClick={() => setVisionOpen(true)}
        disabled={!settings.data || !visionStatus.data || visionStatus.isError}
        title={
          settings.isError
            ? '后台配置加载失败，请先重试'
            : visionStatus.isError
              ? '图片理解状态加载失败，请先重试'
              : undefined
        }
      >
        补充图片理解
      </Button>
    </PostToolbarActions>
  );
  const renderPostActions = (post: AuthorPost) => (
    <Space size={8}>
      <PostOriginalLink noteUrl={post.note_url} />
      <PostCommentCollectionAction post={post} />
      <Button type="link" icon={<LinkOutlined />} onClick={() => setLinkingPostIds([post.id])}>
        关联
      </Button>
    </Space>
  );
  const projectIds = value.projects?.map((project) => project.id) ?? [];
  const tabContent =
    tab === 'reports' ? (
      reports.isError ? (
        <QueryError error={reports.error} retry={() => void reports.refetch()} />
      ) : reports.isPending ? (
        <QueryLoading rows={8} />
      ) : (
        <ReportPanel
          reports={reports.data}
          target={{ type: 'author', id }}
          status={reportStatus.data}
          statusError={reportStatus.error}
          statusLoading={reportStatus.isPending}
          onRetryStatus={() => void reportStatus.refetch()}
          onGenerate={() => setReportOpen(true)}
          onPresentationCreated={handleTaskCreated}
          onGenerateSummary={() => generateDataSummary.mutate()}
          summaryGenerating={generateDataSummary.isPending}
          scopeLabel="作者"
          onOpenPost={(postId) =>
            history.push(
              buildPostDetailPath(postId, {
                source: 'author',
                authorId: id,
                base: postDetailBase,
              }),
            )
          }
        />
      )
    ) : (
      <>
        {visionStatus.isError ? (
          <QueryError error={visionStatus.error} retry={() => void visionStatus.refetch()} />
        ) : null}
        <PostListHeader
          title={`作者帖子（${filteredPosts.length}/${value.posts?.length ?? 0}）`}
          view={view}
          onViewChange={setView}
          showViewLabel
          query={(
            <PostListFilters
              value={postFilters}
              onChange={setPostFilters}
              additionalFilters={[
                {
                  key: 'media_storage',
                  label: '媒体存储状态',
                  ariaLabel: '按媒体存储状态筛选',
                  value: postMediaStorage,
                  options: [
                    { value: 'all', label: '全部媒体状态' },
                    { value: 'remote', label: '远程图片待下载' },
                    { value: 'local', label: '正文图片已本地化' },
                    { value: 'none', label: '无正文图片' },
                  ],
                  onChange: (mediaStorage) =>
                    setPostMediaStorage(mediaStorage as MediaStorageFilter),
                },
              ]}
            />
          )}
        />
        <ProTable<AuthorPost>
          className="post-list-table"
          rowKey="id"
          headerTitle={view === 'list' ? postBatchActions : false}
          columns={columns}
          dataSource={filteredPosts}
          search={false}
          tableViewRender={createPostTableViewRender(
            view,
            (post) =>
              history.push(
                buildPostDetailPath(post.id, {
                  source: 'author',
                  authorId: id,
                  base: postDetailBase,
                }),
              ),
            renderPostActions,
            postRowSelection,
            postBatchActions,
            undefined,
            {
              sort: postSort,
              onSortChange: setPostSort,
              sortOptions: POST_SORT_OPTIONS,
            },
          )}
          onChange={(_, __, sorter, extra) => {
            if (extra.action !== 'sort' || Array.isArray(sorter)) return;
            setPostSort(postSortFromTable(sorter.columnKey ?? sorter.field, sorter.order));
          }}
          scroll={{ x: 1620 }}
          pagination={{
            pageSize: postPageSize,
            onChange: (_, nextPageSize) => setPostPageSize(nextPageSize),
            showSizeChanger: true,
            pageSizeOptions: POST_PAGE_SIZE_OPTIONS.map(String),
            showTotal: (total) => `共 ${total} 篇`,
          }}
          options={
            view === 'list'
              ? { reload: false, density: true, setting: true, fullScreen: true }
              : false
          }
          columnsState={TABLE_COLUMN_PREFERENCES.authorPosts}
          rowSelection={postRowSelection}
          tableAlertRender={false}
          toolBarRender={view === 'list' ? () => [] : false}
        />
      </>
    );

  const pageActions = [
    showBasicInfoUpdate ? (
      <Button
        key="update-basic-info"
        icon={<IdcardOutlined />}
        loading={updatingBasicInfo}
        onClick={() => void updateBasicInfo(value)}
      >
        更新基础信息
      </Button>
    ) : null,
    <Button key="update" icon={<SyncOutlined />} onClick={() => setUpdating(true)}>
      更新帖子信息
    </Button>,
    showProjectAssociation ? (
      <Button key="link" icon={<LinkOutlined />} onClick={() => setLinking(true)}>
        关联到项目
      </Button>
    ) : null,
    value.profile_url ? (
      <Button key="profile" icon={<ExportOutlined />} href={value.profile_url} target="_blank">
        打开主页
      </Button>
    ) : null,
  ];
  const pageContent = (
    <>
      <div className="author-detail-page">
        <Card className="author-profile-card">
          <div className="author-detail-hero">
            <div className="author-detail-identity">
              <Avatar
                size={88}
                src={value.avatar_local_url || value.avatar_url || undefined}
                icon={<UserOutlined />}
              />
              <div className="author-detail-summary">
                <Typography.Title level={2}>
                  {value.display_name || value.author_id}
                </Typography.Title>
                <Typography.Paragraph type="secondary">
                  {value.bio || '暂无作者简介'}
                </Typography.Paragraph>
                {showProjectAssociation ? (
                  <div className="author-detail-projects">
                    <Typography.Text type="secondary">关联项目</Typography.Text>
                    <Space size={[8, 8]} wrap>
                      {value.projects?.length ? (
                        value.projects.map((project) => (
                          <Link key={project.id} to={`/projects/${project.id}`}>
                            <Tag color="blue">{project.name}</Tag>
                          </Link>
                        ))
                      ) : (
                        <Tag>暂未关联项目</Tag>
                      )}
                    </Space>
                  </div>
                ) : null}
              </div>
            </div>
            <section className="author-detail-primary-metrics" aria-label="作者核心数据">
              <Statistic
                title="粉丝"
                value={value.followers_count ?? 0}
                formatter={() => formatNumber(value.followers_count)}
              />
              <Statistic
                title="获赞与收藏"
                value={value.likes_collections_count ?? 0}
                formatter={() => formatNumber(value.likes_collections_count)}
              />
              <Statistic title="帖子（已存/总数）" value={formatAuthorPostCoverage(value)} />
            </section>
          </div>
          <section className="author-detail-secondary" aria-labelledby="author-account-details">
            <Typography.Text id="author-account-details" className="author-detail-section-label">
              账号资料
            </Typography.Text>
            <Descriptions
              size="small"
              colon={false}
              column={{ xs: 1, sm: 2, lg: 3 }}
              items={[
                {
                  key: 'author-id',
                  label: '作者 ID',
                  children: <span className="mono">{value.author_id}</span>,
                },
                { key: 'xhs-id', label: '小红书号', children: value.xhs_id || '—' },
                { key: 'location', label: 'IP 属地', children: value.ip_location || '—' },
                { key: 'following', label: '关注', children: formatNumber(value.following_count) },
                {
                  key: 'post-stats',
                  label: (
                    <Space size={4}>
                      <span>帖子统计</span>
                      <Popover
                        title="帖子统计说明"
                        trigger="click"
                        content={
                          <div className="author-post-stats-help">
                            <Typography.Text type="secondary">数值按以下顺序排列：</Typography.Text>
                            <ol>
                              <li>已获取到详情页的帖子数</li>
                              <li>已获取到图片理解的帖子数</li>
                              <li>总共爬取到的帖子数</li>
                              <li>累计发布的帖子数</li>
                            </ol>
                          </div>
                        }
                      >
                        <Button
                          type="text"
                          size="small"
                          className="author-post-stats-help-button"
                          icon={<QuestionCircleOutlined />}
                          aria-label="查看帖子统计说明"
                        />
                      </Popover>
                    </Space>
                  ),
                  children: (
                    <span className="author-post-stats-value">
                      {formatAuthorPostCollectionStats(collectionStats)}
                    </span>
                  ),
                },
                { key: 'updated', label: '资料更新', children: formatDate(value.updated_at) },
              ]}
            />
          </section>
        </Card>
        <Tabs
          className="detail-section-tabs"
          activeKey={tab}
          onChange={(next) => {
            if (embedded) {
              setEmbeddedTab(next as 'posts' | 'reports');
              return;
            }
            history.push(`${detailBase}/${next}`);
          }}
          items={[
            {
              key: 'posts',
              label: `帖子 ${storedPostCount}`,
              children: tab === 'posts' ? tabContent : undefined,
            },
            {
              key: 'reports',
              label: `报告 ${reports.data?.length ?? 0}`,
              children: tab === 'reports' ? tabContent : undefined,
            },
          ]}
        />
      </div>
      {showProjectAssociation ? (
        <AddToProjectModal
          open={linking}
          entityType="author"
          entityIds={[id]}
          existingProjectIds={projectIds}
          onClose={() => setLinking(false)}
        />
      ) : null}
      <AddToProjectModal
        open={linkingPostIds.length > 0}
        entityType="post"
        entityIds={linkingPostIds}
        onClose={() => setLinkingPostIds([])}
        onSuccess={() => setSelectedPostIds([])}
      />
      <AuthorUpdateModal
        open={updating}
        author={value}
        onClose={() => setUpdating(false)}
        onCreated={handleTaskCreated}
      />
      <ReportRunModal
        target={{ type: 'author', id, name: value.display_name || value.author_id }}
        status={reportStatus.data}
        reports={reports.data || []}
        open={reportOpen}
        onClose={() => setReportOpen(false)}
        onCreated={handleTaskCreated}
      />
      {settings.data && visionStatus.data ? (
        <VisionRunModal
          target={{ type: 'author', id, name: value.display_name || value.author_id }}
          status={visionStatus.data}
          settings={settings.data}
          open={visionOpen}
          onClose={() => setVisionOpen(false)}
          onCreated={handleTaskCreated}
        />
      ) : null}
      <TaskCreatedModal
        task={createdTask}
        onStay={() => setCreatedTask(null)}
        onView={(task) => {
          setCreatedTask(null);
          history.push(`/tasks/${task.id}`);
        }}
      />
    </>
  );
  if (embedded) {
    return <div className="author-detail-embedded">{pageContent}</div>;
  }
  return (
    <PageContainer
      title={value.display_name || value.author_id}
      subTitle={subTitle}
      onBack={showBack ? () => history.push('/authors') : undefined}
      extra={pageActions}
    >
      {pageContent}
    </PageContainer>
  );
}
