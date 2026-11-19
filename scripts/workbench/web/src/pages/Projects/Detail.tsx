import {
  DeleteOutlined,
  EditOutlined,
  EllipsisOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { history, useParams } from '@umijs/max';
import {
  App,
  Button,
  Dropdown,
  Form,
  Input,
  List,
  Modal,
  Result,
  Space,
  Tabs,
  Tag,
  Typography,
} from 'antd';
import type { ReactNode } from 'react';
import { useDeferredValue, useEffect, useMemo, useRef, useState } from 'react';
import AuthorDetailDrawer from '@/features/authors/AuthorDetailDrawer';
import ProjectAuthorBulkUpdateModal from '@/features/authors/ProjectAuthorBulkUpdateModal';
import ProjectAuthorsTable from '@/features/authors/ProjectAuthorsTable';
import PostDetailDrawer from '@/features/posts/PostDetailDrawer';
import ProjectPostsTable from '@/features/posts/ProjectPostsTable';
import {
  PROJECT_POST_SORT_OPTIONS,
  type PostCardSort,
} from '@/features/posts/PostView';
import {
  readPostPageSize,
  savePostPageSize,
} from '@/features/posts/postListPreferences';
import { useListSort } from '@/features/preferences/listSortPreferences';
import ProjectReferencePickerModal from '@/features/references/ProjectReferencePickerModal';
import ProjectEditModal from '@/features/projects/ProjectEditModal';
import type { ProjectEditValues } from '@/features/projects/ProjectEditModal';
import ProjectKeywordsTable from '@/features/projects/ProjectKeywordsTable';
import { clearKeywordSuggestionCache } from '@/features/projects/keywordSuggestionCache';
import ReportPanel from '@/features/reports/ReportPanel';
import ReportRunModal from '@/features/reports/ReportRunModal';
import CreateResearchTaskModal from '@/features/research/CreateResearchTaskModal';
import RerunResearchModal from '@/features/research/RerunResearchModal';
import ActiveTaskPanel from '@/features/tasks/ActiveTaskPanel';
import ProjectTasksTable from '@/features/tasks/ProjectTasksTable';
import VisionRunModal from '@/features/vision/VisionRunModal';
import { QueryError, QueryLoading } from '@/components/QueryState';
import TaskCreatedModal from '@/components/TaskCreatedModal';
import TaskStatusTag from '@/components/TaskStatusTag';
import { ApiError, apiService, isProjectAuthorPostConflict } from '@/services/api';
import { projectFinalSyncQueryKeys, queryKeys } from '@/services/queryKeys';
import type {
  Project,
  ProjectAuthorPostConflict,
  ProjectKeywordSource,
  Post,
  ProjectPostQuery,
  Task,
  TaskReceipt,
} from '@/types';
import { activeTaskStatuses } from '@/utils/format';
import { canDeleteProject, isProjectTaskStateUnknown } from '@/utils/projectTasks';
import { buildPostDetailPath } from '@/utils/postNavigation';
import { activeTaskIds, didActiveTaskSettle } from '@/utils/taskPolling';

const tabs = ['keywords', 'report', 'posts', 'authors', 'tasks'] as const;
type ProjectTab = (typeof tabs)[number];

const DEFAULT_PROJECT_POST_QUERY: ProjectPostQuery = {
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

const PROJECT_POST_SORT_VALUES = PROJECT_POST_SORT_OPTIONS.map(({ value }) => value);

interface PendingReferenceRemoval {
  postIds: number[];
  authorIds: number[];
  confirmRemoveAuthorPosts?: boolean;
}

type AuthorPostConflictState = ProjectAuthorPostConflict & {
  authorIds: number[];
};

function validTab(value?: string): ProjectTab {
  return tabs.includes(value as ProjectTab) ? (value as ProjectTab) : 'report';
}

export interface ProjectDetailPageProps {
  projectId?: number;
  routeBase?: string;
  showBack?: boolean;
}

export default function ProjectDetailPage({
  projectId,
  routeBase,
  showBack = projectId === undefined,
}: ProjectDetailPageProps = {}) {
  const params = useParams<{ id?: string; tab?: string }>();
  const id = projectId ?? Number(params.id);
  const tab = validTab(params.tab);
  const detailBase = routeBase ?? `/projects/${id}`;
  const queryClient = useQueryClient();
  const { message } = App.useApp();
  const [authorId, setAuthorId] = useState<number>();
  const [openedPost, setOpenedPost] = useState<Post>();
  const [visionOpen, setVisionOpen] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  const [createTaskOpen, setCreateTaskOpen] = useState(false);
  const [taskInitialKeywords, setTaskInitialKeywords] = useState<string[]>([]);
  const [authorBulkUpdateOpen, setAuthorBulkUpdateOpen] = useState(false);
  const [rerunOpen, setRerunOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [createdTask, setCreatedTask] = useState<TaskReceipt | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteName, setDeleteName] = useState('');
  const [referenceType, setReferenceType] = useState<'post' | 'author'>();
  const [authorPostConflict, setAuthorPostConflict] =
    useState<AuthorPostConflictState | null>(null);
  const [pendingTaskId, setPendingTaskId] = useState<string>();
  const [projectPostSort, setProjectPostSort] = useListSort<PostCardSort>(
    'posts.project',
    PROJECT_POST_SORT_VALUES,
    'default',
  );
  const [postQuery, setPostQuery] = useState<ProjectPostQuery>(() => ({
    ...DEFAULT_PROJECT_POST_QUERY,
    page_size: readPostPageSize(),
    sort: projectPostSort,
  }));
  const deferredPostQuery = useDeferredValue(postQuery);
  const previousProjectTasks = useRef<
    | {
        projectId: number;
        activeIds: ReadonlySet<string>;
      }
    | undefined
  >(undefined);

  useEffect(() => {
    setPostQuery((current) =>
      current.sort === projectPostSort
        ? current
        : { ...current, page: 1, sort: projectPostSort },
    );
  }, [projectPostSort]);

  const tasks = useQuery({
    queryKey: queryKeys.projectTasks(id),
    queryFn: ({ signal }) => apiService.projectTasks(id, signal),
    enabled: Number.isInteger(id) && id > 0,
    refetchInterval: (query) =>
      query.state.data?.some((task) => activeTaskStatuses.has(task.status)) ? 2_000 : false,
  });
  const isActive = tasks.data?.some((task) => activeTaskStatuses.has(task.status)) || false;
  const project = useQuery({
    queryKey: queryKeys.project(id),
    queryFn: ({ signal }) => apiService.project(id, signal),
    enabled: Number.isInteger(id) && id > 0,
    refetchInterval: isActive ? 4_000 : false,
  });
  const health = useQuery({
    queryKey: queryKeys.health,
    queryFn: ({ signal }) => apiService.health(signal),
    enabled: Number.isInteger(id) && id > 0 && tab === 'keywords',
    staleTime: 15_000,
  });
  const posts = useQuery({
    queryKey: queryKeys.projectPosts(id, deferredPostQuery),
    queryFn: ({ signal }) => apiService.projectPosts(id, deferredPostQuery, signal),
    enabled: Number.isInteger(id) && id > 0 && tab === 'posts',
    placeholderData: keepPreviousData,
  });
  const postCoverage = useQuery({
    queryKey: queryKeys.projectPostCoverage(id),
    queryFn: ({ signal }) => apiService.projectPostCoverage(id, signal),
    enabled: Number.isInteger(id) && id > 0 && tab === 'posts',
  });
  const authors = useQuery({
    queryKey: queryKeys.projectAuthors(id),
    queryFn: ({ signal }) => apiService.projectAuthors(id, signal),
    enabled:
      Number.isInteger(id) && id > 0 &&
      (tab === 'authors' || authorBulkUpdateOpen || rerunOpen || referenceType === 'author'),
  });
  const reports = useQuery({
    queryKey: queryKeys.projectReports(id),
    queryFn: ({ signal }) => apiService.projectReports(id, signal),
    enabled: Number.isInteger(id) && id > 0 && tab === 'report',
    refetchInterval: (query) =>
      query.state.data?.some((report) => report.status === 'generating') ? 2_000 : false,
  });
  const keywords = useQuery({
    queryKey: queryKeys.projectKeywords(id),
    queryFn: ({ signal }) => apiService.projectKeywords(id, signal),
    enabled: Number.isInteger(id) && id > 0 && (tab === 'keywords' || createTaskOpen),
  });
  const visionStatus = useQuery({
    queryKey: queryKeys.projectVision(id),
    queryFn: ({ signal }) => apiService.projectVisionStatus(id, signal),
    enabled: Number.isInteger(id) && id > 0 && (tab === 'posts' || visionOpen),
  });
  const reportStatus = useQuery({
    queryKey: queryKeys.projectReportStatus(id),
    queryFn: ({ signal }) => apiService.projectReportStatus(id, signal),
    enabled: Number.isInteger(id) && id > 0 && (tab === 'report' || reportOpen),
  });
  const generateDataSummary = useMutation({
    mutationFn: () => apiService.generateProjectDataSummary(id),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.projectReports(id), exact: true }),
        queryClient.invalidateQueries({ queryKey: queryKeys.project(id), exact: true }),
      ]);
      message.success('数据摘要已生成');
    },
    onError: (error) => message.error(error.message),
  });
  const settings = useQuery({
    queryKey: queryKeys.settings,
    queryFn: ({ signal }) => apiService.settings(signal),
  });
  const activeTasks = useMemo(
    () => tasks.data?.filter((task) => activeTaskStatuses.has(task.status)) || [],
    [tasks.data],
  );
  const taskStateUnknown = isProjectTaskStateUnknown(tasks);
  const researchTask = tasks.data?.find((task) => task.task_type === 'research');
  const handleTaskCreated = (task: TaskReceipt) => {
    setCreatedTask(task);
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.projectTasks(id), exact: true }),
      queryClient.invalidateQueries({ queryKey: queryKeys.projectReports(id), exact: true }),
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks, exact: true }),
      queryClient.invalidateQueries({ queryKey: queryKeys.task(task.id), exact: true }),
    ]);
  };

  useEffect(() => {
    if (!tasks.data) return;
    const currentActiveIds = activeTaskIds(tasks.data);
    const previousActiveIds =
      previousProjectTasks.current?.projectId === id
        ? previousProjectTasks.current.activeIds
        : undefined;
    const shouldFinalSync = didActiveTaskSettle(previousActiveIds, currentActiveIds);
    previousProjectTasks.current = { projectId: id, activeIds: currentActiveIds };
    if (!shouldFinalSync) return;

    void Promise.all(
      projectFinalSyncQueryKeys(id).map((queryKey) =>
        queryClient.invalidateQueries({ queryKey, exact: false }),
      ),
    );
  }, [id, queryClient, tasks.data]);

  const cancelTask = useMutation({
    mutationFn: apiService.cancelTask,
    onMutate: (taskId) => setPendingTaskId(taskId),
    onSuccess: async (_, taskId) => {
      message.success('任务已取消');
      queryClient.setQueryData<Task[]>(queryKeys.projectTasks(id), (current) =>
        current?.filter((task) => task.id !== taskId),
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.projectTasks(id), exact: true }),
        queryClient.invalidateQueries({ queryKey: queryKeys.project(id), exact: true }),
        queryClient.invalidateQueries({ queryKey: queryKeys.tasks, exact: true }),
        queryClient.invalidateQueries({ queryKey: queryKeys.task(taskId), exact: true }),
        queryClient.invalidateQueries({ queryKey: queryKeys.taskEvents(taskId), exact: true }),
        queryClient.invalidateQueries({ queryKey: queryKeys.projects, exact: true }),
        queryClient.invalidateQueries({ queryKey: queryKeys.stats, exact: true }),
      ]);
    },
    onError: (error) => message.error(error.message),
    onSettled: () => setPendingTaskId(undefined),
  });
  const retryTask = useMutation({
    mutationFn: apiService.retryTask,
    onMutate: (taskId) => setPendingTaskId(taskId),
    onSuccess: (next) => {
      handleTaskCreated(next);
    },
    onError: (error) => message.error(error.message),
    onSettled: () => setPendingTaskId(undefined),
  });
  const removeProject = useMutation({
    mutationFn: () => apiService.deleteProject(id),
    onSuccess: () => {
      clearKeywordSuggestionCache(id);
      message.success('项目已删除；全局帖子和作者主数据已保留');
      queryClient.invalidateQueries({ queryKey: queryKeys.projects });
      queryClient.removeQueries({ queryKey: queryKeys.project(id), exact: true });
      history.push(routeBase ?? '/projects');
    },
    onError: (error) => message.error(error.message),
  });
  const updateProject = useMutation({
    mutationFn: (values: ProjectEditValues) => apiService.updateProject(id, values),
    onSuccess: async (updated) => {
      clearKeywordSuggestionCache(id);
      setEditOpen(false);
      queryClient.setQueryData<Project>(queryKeys.project(id), updated);
      message.success('项目已更新');
      await queryClient.invalidateQueries({ queryKey: queryKeys.projects });
    },
    onError: (error) =>
      message.error(error instanceof Error ? error.message : '更新项目失败'),
  });
  const removeReferences = useMutation({
    mutationFn: (values: PendingReferenceRemoval) =>
      apiService.removeProjectReferences(id, {
        post_ids: values.postIds,
        author_ids: values.authorIds,
        confirm_remove_author_posts: values.confirmRemoveAuthorPosts,
      }),
    onSuccess: async (result) => {
      setAuthorPostConflict(null);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.projects }),
        queryClient.invalidateQueries({ queryKey: queryKeys.posts }),
        queryClient.invalidateQueries({ queryKey: queryKeys.authors }),
        queryClient.invalidateQueries({ queryKey: queryKeys.project(id), exact: true }),
        queryClient.invalidateQueries({ queryKey: queryKeys.projectPosts(id), exact: false }),
        queryClient.invalidateQueries({ queryKey: queryKeys.projectPostCoverage(id), exact: true }),
        queryClient.invalidateQueries({ queryKey: queryKeys.projectAuthors(id), exact: true }),
        queryClient.invalidateQueries({ queryKey: queryKeys.projectVision(id), exact: true }),
        queryClient.invalidateQueries({ queryKey: queryKeys.projectReportStatus(id), exact: true }),
      ]);
      const parts = [
        result.removed_author_count ? `${result.removed_author_count} 位作者` : '',
        result.removed_post_count ? `${result.removed_post_count} 篇帖子` : '',
      ].filter(Boolean);
      message.success(parts.length ? `已取消关联 ${parts.join('、')}` : '没有可取消的关联');
    },
    onError: (error, variables) => {
      if (
        error instanceof ApiError &&
        error.status === 409 &&
        isProjectAuthorPostConflict(error.payload)
      ) {
        setAuthorPostConflict({ ...error.payload, authorIds: variables.authorIds });
        return;
      }
      message.error(error instanceof Error ? error.message : '取消关联失败');
    },
  });
  const addKeywords = useMutation({
    mutationFn: ({
      values,
      source,
    }: {
      values: string[];
      source?: ProjectKeywordSource;
    }) => apiService.addProjectKeywords(id, values, source),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.projectKeywords(id), exact: true }),
        queryClient.invalidateQueries({ queryKey: queryKeys.project(id), exact: true }),
        queryClient.invalidateQueries({ queryKey: queryKeys.projects }),
      ]);
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '添加关键词失败'),
  });
  const removeKeywords = useMutation({
    mutationFn: (keywordIds: number[]) => apiService.removeProjectKeywords(id, keywordIds),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.projectKeywords(id), exact: true }),
        queryClient.invalidateQueries({ queryKey: queryKeys.project(id), exact: true }),
        queryClient.invalidateQueries({ queryKey: queryKeys.projects }),
      ]);
      message.success('关键词已移除');
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '移除关键词失败'),
  });

  if (!Number.isInteger(id) || id <= 0) {
    return (
      <Result
        status="404"
        title="项目不存在"
        extra={<Button onClick={() => history.push('/projects')}>返回项目列表</Button>}
      />
    );
  }
  if (project.isPending)
    return (
      <PageContainer>
        <QueryLoading rows={8} />
      </PageContainer>
    );
  if (project.isError) {
    return (
      <PageContainer>
        <QueryError error={project.error} retry={() => project.refetch()} />
      </PageContainer>
    );
  }
  const value = project.data;
  const backPath = '/projects';
  const latestTaskStatus = taskStateUnknown
    ? undefined
    : (value.latest_task_status ?? tasks.data?.[0]?.status);
  const taskStateLabel = tasks.isPending ? '任务状态加载中' : '任务状态未知';
  const deleteAllowed = canDeleteProject({
    taskStateUnknown,
    activeTaskCount: activeTasks.length,
    confirmationMatches: deleteName === value.name,
  });
  const goTask = (taskId: string) => history.push(`${detailBase}/tasks/${taskId}`);
  let content: ReactNode;
  if (tab === 'keywords') {
    content = keywords.isError ? (
      <QueryError error={keywords.error} retry={() => keywords.refetch()} />
    ) : keywords.isPending ? (
      <QueryLoading rows={6} />
    ) : (
      <ProjectKeywordsTable
        project={value}
        keywords={keywords.data}
        loading={keywords.isFetching}
        aiAvailable={health.data?.ai_capabilities?.keyword_suggestions ?? true}
        onAdd={(values, source) => addKeywords.mutateAsync({ values, source })}
        onRemove={(ids) => removeKeywords.mutateAsync(ids)}
        onSearch={(values) => {
          setTaskInitialKeywords(values);
          setCreateTaskOpen(true);
        }}
      />
    );
  } else if (tab === 'report') {
    content = reports.isError ? (
      <QueryError error={reports.error} retry={() => reports.refetch()} />
    ) : reports.isPending ? (
      <QueryLoading rows={8} />
    ) : (
      <ReportPanel
        reports={reports.data}
        target={{ type: 'project', id: value.id }}
        status={reportStatus.data}
        statusError={reportStatus.error}
        statusLoading={reportStatus.isPending}
        onRetryStatus={() => void reportStatus.refetch()}
        onGenerate={() => setReportOpen(true)}
        onPresentationCreated={handleTaskCreated}
        onGenerateSummary={() => generateDataSummary.mutate()}
        summaryGenerating={generateDataSummary.isPending}
        onOpenPost={(postId) =>
          history.push(buildPostDetailPath(postId, { source: 'project', projectId: id }))
        }
      />
    );
  } else if (tab === 'posts') {
    content = posts.isError ? (
      <QueryError error={posts.error} retry={() => posts.refetch()} />
    ) : posts.isPending ? (
      <QueryLoading rows={8} />
    ) : (
      <ProjectPostsTable
        posts={posts.data.items}
        total={posts.data.total}
        projectTotal={value.post_count ?? posts.data.total}
        page={postQuery.page}
        pageSize={postQuery.page_size}
        loading={posts.isFetching || deferredPostQuery !== postQuery}
        query={postQuery}
        onQueryChange={(next) => {
          if (next.sort) setProjectPostSort(next.sort as PostCardSort);
          setPostQuery((current) => ({ ...current, ...next }));
        }}
        onPageChange={(page, pageSize) => {
          const persistedPageSize = savePostPageSize(pageSize);
          setPostQuery((current) => ({ ...current, page, page_size: persistedPageSize }));
        }}
        projectId={id}
        detailTtlDays={settings.data?.detail_ttl_days}
        delaySettings={settings.data}
        onTaskCreated={handleTaskCreated}
        onOpen={setOpenedPost}
        onLink={() => setReferenceType('post')}
        onUnlink={(postIds) => removeReferences.mutateAsync({ postIds, authorIds: [] })}
        onVision={() => setVisionOpen(true)}
        visionDisabled={!settings.data || !visionStatus.data || visionStatus.isError}
        visionDisabledReason={
          settings.isError
            ? '后台配置加载失败，请先重试'
            : visionStatus.isError
              ? '图片理解状态加载失败，请先重试'
              : undefined
        }
        coverage={postCoverage.data}
      />
    );
  } else if (tab === 'authors') {
    content = authors.isError ? (
      <QueryError error={authors.error} retry={() => authors.refetch()} />
    ) : authors.isPending ? (
      <QueryLoading rows={8} />
    ) : (
      <ProjectAuthorsTable
        authors={authors.data}
        onSelect={setAuthorId}
        onLink={() => setReferenceType('author')}
        onUnlink={(authorIds) =>
          removeReferences.mutate({ postIds: [], authorIds })
        }
        onBulkUpdate={() => setAuthorBulkUpdateOpen(true)}
      />
    );
  } else {
    content = tasks.isError ? (
      <QueryError error={tasks.error} retry={() => tasks.refetch()} />
    ) : tasks.isPending ? (
      <QueryLoading rows={8} />
    ) : (
      <ProjectTasksTable
        tasks={tasks.data}
        onView={goTask}
        onCancel={(taskId) => cancelTask.mutate(taskId)}
        onRetry={(taskId) => retryTask.mutate(taskId)}
        pendingTaskId={pendingTaskId}
      />
    );
  }

  return (
    <PageContainer
      title={value.name}
      subTitle="调研项目"
      tags={
        taskStateUnknown ? (
          <Tag color={tasks.isError ? 'error' : 'processing'}>{taskStateLabel}</Tag>
        ) : (
          <TaskStatusTag status={latestTaskStatus} />
        )
      }
      content={value.description || '项目中的帖子、作者、任务和报告版本统一沉淀在这里。'}
      onBack={showBack ? () => history.push(backPath) : undefined}
      extra={[
        <Button
          key="edit"
          icon={<EditOutlined />}
          onClick={() => setEditOpen(true)}
        >
          编辑项目
        </Button>,
        <Button
          key="create-task"
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => {
            setTaskInitialKeywords([]);
            setCreateTaskOpen(true);
          }}
        >
          发起任务
        </Button>,
        <Dropdown
          key="more"
          menu={{
            items: [
              {
                key: 'rerun',
                label: '按上次配置重跑',
                icon: (<ReloadOutlined />),
                disabled: !researchTask || !settings.data || taskStateUnknown,
                title: tasks.isError
                  ? '任务状态加载失败，请先重试'
                  : tasks.isPending
                    ? '正在加载任务状态'
                    : settings.isError
                      ? '后台配置加载失败，请先重试'
                      : undefined,
                onClick: () => setRerunOpen(true),
              },
              {
                key: 'delete',
                label: '删除项目',
                icon: (<DeleteOutlined />),
                danger: true,
                disabled: taskStateUnknown,
                onClick: () => {
                  setDeleteName('');
                  setDeleteOpen(true);
                },
              },
            ],
          }}
        >
          <Button icon={<EllipsisOutlined />} aria-label="更多项目操作" />
        </Dropdown>,
      ]}
    >
      <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
        {settings.isError ? (
          <QueryError error={settings.error} retry={() => void settings.refetch()} />
        ) : null}
        {tasks.isError && tab !== 'tasks' ? (
          <QueryError error={tasks.error} retry={() => void tasks.refetch()} />
        ) : null}
        <ActiveTaskPanel tasks={activeTasks} onView={goTask} />
        <Tabs
          className="detail-section-tabs"
          activeKey={tab}
          onChange={(next) => history.push(`${detailBase}/${next}`)}
          items={[
            {
              key: 'keywords',
              label: `关键词 ${value.keyword_count ?? 0}`,
              children: tab === 'keywords' ? content : undefined,
            },
            {
              key: 'report',
              label: `报告 ${value.report_count ?? 0}`,
              children: tab === 'report' ? content : undefined,
            },
            {
              key: 'posts',
              label: `帖子 ${value.post_count ?? 0}`,
              children:
                tab === 'posts' ? (
                  <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
                    {visionStatus.isError ? (
                      <QueryError
                        error={visionStatus.error}
                        retry={() => void visionStatus.refetch()}
                      />
                    ) : null}
                    {content}
                  </Space>
                ) : undefined,
            },
            {
              key: 'authors',
              label: `作者 ${value.author_count ?? 0}`,
              children: tab === 'authors' ? content : undefined,
            },
            {
              key: 'tasks',
              label: taskStateUnknown ? '任务 —' : `任务 ${tasks.data?.length ?? 0}`,
              children: tab === 'tasks' ? content : undefined,
            },
          ]}
        />
      </Space>
      <AuthorDetailDrawer authorId={authorId} onClose={() => setAuthorId(undefined)} />
      <ProjectEditModal
        project={value}
        open={editOpen}
        saving={updateProject.isPending}
        onCancel={() => {
          if (!updateProject.isPending) setEditOpen(false);
        }}
        onSave={(values) => updateProject.mutate(values)}
      />
      {referenceType ? (
        <ProjectReferencePickerModal
          open
          projectId={id}
          entityType={referenceType}
          onClose={() => setReferenceType(undefined)}
        />
      ) : null}
      <PostDetailDrawer summary={openedPost} onClose={() => setOpenedPost(undefined)} />
      {settings.data && visionStatus.data && (
        <VisionRunModal
          target={{ type: 'project', id: value.id, name: value.name }}
          status={visionStatus.data}
          settings={settings.data}
          open={visionOpen}
          onClose={() => setVisionOpen(false)}
          onCreated={handleTaskCreated}
        />
      )}
      {reportStatus.data ? (
        <ReportRunModal
          target={{ type: 'project', id: value.id, name: value.name }}
          status={reportStatus.data}
          reports={reports.data || []}
          open={reportOpen}
          onClose={() => setReportOpen(false)}
          onCreated={handleTaskCreated}
        />
      ) : null}
      {settings.data ? (
        <CreateResearchTaskModal
          project={value}
          settings={settings.data}
          open={createTaskOpen}
          initialKeywords={taskInitialKeywords}
          onClose={() => setCreateTaskOpen(false)}
          onCreated={handleTaskCreated}
        />
      ) : null}
      {settings.data && authors.data ? (
        <ProjectAuthorBulkUpdateModal
          project={value}
          authors={authors.data}
          settings={settings.data}
          open={authorBulkUpdateOpen}
          onClose={() => setAuthorBulkUpdateOpen(false)}
          onCreated={handleTaskCreated}
        />
      ) : null}
      {researchTask && settings.data && (
        <RerunResearchModal
          project={value}
          sourceTask={researchTask}
          settings={settings.data}
          authors={authors.data || []}
          open={rerunOpen}
          onClose={() => setRerunOpen(false)}
          onCreated={handleTaskCreated}
        />
      )}
      <TaskCreatedModal
        task={createdTask}
        onStay={() => setCreatedTask(null)}
        onView={(task) => {
          setCreatedTask(null);
          history.push(`/tasks/${task.id}`);
        }}
      />
      <Modal
        title="确认移除作者及相关帖子"
        open={Boolean(authorPostConflict)}
        onCancel={() => setAuthorPostConflict(null)}
        onOk={() => {
          if (!authorPostConflict) return;
          removeReferences.mutate({
            postIds: [],
            authorIds: authorPostConflict.authorIds,
            confirmRemoveAuthorPosts: true,
          });
        }}
        okText="确认移除作者及相关帖子"
        cancelText="取消"
        okButtonProps={{ danger: true }}
        confirmLoading={removeReferences.isPending}
        destroyOnHidden
      >
        {authorPostConflict ? (
          <>
            <Typography.Paragraph>
              选中的作者中有 {authorPostConflict.authors.length} 位仍在本项目下有帖子，
              共 {authorPostConflict.total_post_count} 篇帖子会一并从项目移除。
            </Typography.Paragraph>
            <Typography.Paragraph type="secondary">
              这里只移除当前项目中的作者/帖子关联，不会删除全局作者和全局帖子数据。
            </Typography.Paragraph>
            <List
              size="small"
              dataSource={authorPostConflict.authors}
              renderItem={(author) => (
                <List.Item>
                  <Typography.Text>{author.name}</Typography.Text>
                  <Typography.Text type="secondary">
                    {author.project_post_count} 篇帖子
                  </Typography.Text>
                </List.Item>
              )}
            />
          </>
        ) : null}
      </Modal>
      <Modal
        title="确认删除项目"
        open={deleteOpen}
        onCancel={() => setDeleteOpen(false)}
        onOk={() => {
          if (deleteAllowed) removeProject.mutate();
        }}
        okText="删除项目"
        cancelText="取消"
        confirmLoading={removeProject.isPending}
        okButtonProps={{ danger: true, disabled: !deleteAllowed }}
        destroyOnHidden
      >
        {taskStateUnknown ? (
          <Result
            status="warning"
            title={tasks.isPending ? '正在确认项目任务状态' : '无法确认项目任务状态'}
            subTitle={
              tasks.isPending
                ? '任务状态加载完成后才能删除项目。'
                : '请先重试任务数据，确认没有活跃任务后再删除。'
            }
            extra={
              tasks.isError ? (
                <Button onClick={() => void tasks.refetch()}>重试任务数据</Button>
              ) : undefined
            }
          />
        ) : activeTasks.length > 0 ? (
          <Result
            status="warning"
            title="项目仍有活跃任务"
            subTitle="请先等待任务结束或在任务详情中取消。"
          />
        ) : (
          <>
            <Typography.Paragraph>
              项目关系和报告会被删除；关联任务会转为独立任务，全局帖子与作者主数据会保留。
            </Typography.Paragraph>
            <Form layout="vertical">
              <Form.Item
                label={`请输入完整项目名称以确认：${value.name}`}
                htmlFor={`project-delete-confirmation-${value.id}`}
                validateStatus={deleteName && deleteName !== value.name ? 'error' : undefined}
                help={
                  deleteName && deleteName !== value.name
                    ? '输入内容与项目名称不一致'
                    : undefined
                }
              >
                <Input
                  id={`project-delete-confirmation-${value.id}`}
                  value={deleteName}
                  onChange={(event) => setDeleteName(event.target.value)}
                  autoComplete="off"
                />
              </Form.Item>
            </Form>
          </>
        )}
      </Modal>
    </PageContainer>
  );
}
