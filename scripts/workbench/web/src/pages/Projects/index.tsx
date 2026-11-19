import { EllipsisOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ActionType, ProColumns } from '@ant-design/pro-components';
import { PageContainer, ProTable } from '@ant-design/pro-components';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { history, Link } from '@umijs/max';
import {
  Alert,
  App,
  Button,
  Dropdown,
  Empty,
  Input,
  Progress,
  Select,
  Typography,
} from 'antd';
import { useEffect, useRef, useState } from 'react';
import { QueryError } from '@/components/QueryState';
import TaskStatusTag from '@/components/TaskStatusTag';
import ProjectDeleteAction from '@/features/projects/ProjectDeleteAction';
import ProjectEditModal from '@/features/projects/ProjectEditModal';
import type { ProjectEditValues } from '@/features/projects/ProjectEditModal';
import { clearKeywordSuggestionCache } from '@/features/projects/keywordSuggestionCache';
import {
  tableSortFromChange,
  tableSortOrder,
  useListSort,
} from '@/features/preferences/listSortPreferences';
import { apiService } from '@/services/api';
import { queryKeys } from '@/services/queryKeys';
import type { Project } from '@/types';
import {
  activeTaskStatuses,
  formatDate,
  formatNumber,
  taskPercent,
  taskPhaseLabels,
  taskStatusLabels,
  taskTypeLabels,
} from '@/utils/format';
import {
  buildProjectTaskRows,
  countActiveProjectTasks,
  filterProjectTaskRows,
  isProjectTaskStateUnknown,
  type ProjectTaskRow,
  type ProjectTaskStatusFilter,
} from '@/utils/projectTasks';
import './index.css';

const { Text } = Typography;

const ACTIVE_POLL_INTERVAL = 5_000;
const IDLE_POLL_INTERVAL = 15_000;

interface ProjectSearchParams {
  current?: number;
  pageSize?: number;
  name?: string;
  task_status?: ProjectTaskStatusFilter;
  refreshToken?: string;
}

type TaskStatusFilterValue = ProjectTaskStatusFilter | 'all';

const taskStatusValueEnum: Record<ProjectTaskStatusFilter, { text: string }> = {
  not_started: { text: '未运行' },
  queued: { text: taskStatusLabels.queued },
  running: { text: taskStatusLabels.running },
  waiting_login: { text: taskStatusLabels.waiting_login },
  completed: { text: taskStatusLabels.completed },
  partial: { text: taskStatusLabels.partial },
  failed: { text: taskStatusLabels.failed },
};

const PROJECT_TABLE_SORTS = [
  'default',
  'posts:asc',
  'posts:desc',
  'authors:asc',
  'authors:desc',
  'updated:asc',
  'updated:desc',
] as const;

function sortProjectRows(
  rows: ProjectTaskRow[],
  preference: (typeof PROJECT_TABLE_SORTS)[number],
): ProjectTaskRow[] {
  if (preference === 'default') return rows;
  const [field, direction] = preference.split(':');
  const multiplier = direction === 'desc' ? -1 : 1;
  return [...rows].sort((left, right) => {
    let result = 0;
    if (field === 'posts') result = (left.post_count ?? 0) - (right.post_count ?? 0);
    else if (field === 'authors') result = (left.author_count ?? 0) - (right.author_count ?? 0);
    else if (field === 'updated') result = left.updated_at.localeCompare(right.updated_at);
    return result * multiplier;
  });
}

export default function ProjectsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const actionRef = useRef<ActionType | undefined>(undefined);
  const [filters, setFilters] = useState<ProjectSearchParams>({});
  const [tableSort, setTableSort] = useListSort(
    'projects.global',
    PROJECT_TABLE_SORTS,
    'default',
  );
  const [editingProject, setEditingProject] = useState<ProjectTaskRow>();
  const [deletingProject, setDeletingProject] = useState<ProjectTaskRow>();
  const projectsQuery = useQuery({
    queryKey: queryKeys.projects,
    queryFn: ({ signal }) => apiService.projects(signal),
    refetchInterval: IDLE_POLL_INTERVAL,
    placeholderData: keepPreviousData,
  });
  const tasksQuery = useQuery({
    queryKey: queryKeys.tasks,
    queryFn: ({ signal }) => apiService.tasks(signal),
    refetchInterval: (query) =>
      query.state.data?.some((task) => activeTaskStatuses.has(task.status))
        ? ACTIVE_POLL_INTERVAL
        : IDLE_POLL_INTERVAL,
    placeholderData: keepPreviousData,
  });

  const removeProject = useMutation({
    mutationFn: (project: ProjectTaskRow) => apiService.deleteProject(project.id),
    onSuccess: async (_, project) => {
      setDeletingProject(undefined);
      clearKeywordSuggestionCache(project.id);
      message.success(`项目“${project.name}”已删除；全局帖子和作者已保留`);
      queryClient.removeQueries({ queryKey: queryKeys.project(project.id) });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.projects }),
        queryClient.invalidateQueries({ queryKey: queryKeys.tasks }),
        queryClient.invalidateQueries({ queryKey: queryKeys.stats }),
      ]);
    },
    onError: (error) => {
      message.error(error instanceof Error ? error.message : '删除项目失败');
    },
  });
  const updateProject = useMutation({
    mutationFn: ({
      projectId,
      values,
    }: {
      projectId: number;
      values: ProjectEditValues;
    }) => apiService.updateProject(projectId, values),
    onSuccess: async (updated) => {
      clearKeywordSuggestionCache(updated.id);
      setEditingProject(undefined);
      queryClient.setQueryData<Project>(queryKeys.project(updated.id), updated);
      queryClient.setQueryData<Project[]>(queryKeys.projects, (current) =>
        current?.map((item) => (item.id === updated.id ? updated : item)),
      );
      message.success('项目已更新');
      await queryClient.invalidateQueries({ queryKey: queryKeys.projects });
    },
    onError: (error) => {
      message.error(error instanceof Error ? error.message : '更新项目失败');
    },
  });

  const projectRows = buildProjectTaskRows(
    projectsQuery.data ?? [],
    tasksQuery.data ?? [],
  );
  const activeCount = countActiveProjectTasks(projectRows);
  const hasInitialError = projectsQuery.isError && !projectsQuery.data;
  const hasBackgroundError =
    (projectsQuery.isError && Boolean(projectsQuery.data)) || tasksQuery.isError;
  const taskStateUnknown = isProjectTaskStateUnknown(tasksQuery);
  const refreshToken = `${projectsQuery.dataUpdatedAt}-${tasksQuery.dataUpdatedAt}`;
  const projectRowsRef = useRef(projectRows);
  projectRowsRef.current = projectRows;
  const refreshing = projectsQuery.isFetching || tasksQuery.isFetching;

  useEffect(() => {
    actionRef.current?.reload();
  }, [refreshToken]);

  useEffect(() => {
    actionRef.current?.reloadAndRest?.();
  }, [filters, tableSort]);

  const refreshProjects = () => {
    void Promise.all([projectsQuery.refetch(), tasksQuery.refetch()]);
  };

  const columns: ProColumns<ProjectTaskRow>[] = [
    {
      title: '项目名称',
      dataIndex: 'name',
      width: 300,
      fixed: 'left',
      ellipsis: true,
      render: (_, project) => {
        const description = project.description || '暂无项目说明';
        return (
          <div className="projects-page__name">
            <Link
              className="projects-page__name-link"
              to={`/projects/${project.id}`}
              aria-label={`进入项目详情：${project.name}`}
            >
              {project.name}
            </Link>
            <Text
              className="projects-page__description"
              type="secondary"
              ellipsis={{ tooltip: description }}
            >
              {description}
            </Text>
          </div>
        );
      },
    },
    {
      title: '任务状态与进度',
      dataIndex: 'task_status',
      width: 228,
      valueType: 'select',
      valueEnum: taskStatusValueEnum,
      render: (_, project) => {
        if (!project.active_tasks.length) {
          return (
            <div className="projects-page__task-status-summary">
              <TaskStatusTag status={project.task_status} />
              <Text type="secondary">无活跃任务</Text>
            </div>
          );
        }
        return (
          <div className="projects-page__task-status">
            <div className="projects-page__task-status-summary">
              <TaskStatusTag status={project.task_status} />
              <Text type="secondary">{project.active_tasks.length} 个活跃任务</Text>
            </div>
            <div className="projects-page__active-tasks">
              {project.active_tasks.map((task) => {
                const percent = taskPercent(task);
                return (
                  <div className="projects-page__active-task" key={task.id}>
                    <Link
                      className="projects-page__task-link"
                      to={`/tasks/${task.id}`}
                      aria-label={`查看${project.name}的活跃任务，当前进度 ${percent}%`}
                    >
                      <Progress
                        percent={percent}
                        size="small"
                        showInfo={false}
                        status={task.status === 'waiting_login' ? 'exception' : 'active'}
                      />
                      <span className="projects-page__task-phase">
                        <span>
                          {taskTypeLabels[task.task_type]} ·{' '}
                          {taskPhaseLabels[task.current_phase] ?? task.current_phase ?? '准备任务'}
                        </span>
                        <span>{percent}%</span>
                      </span>
                    </Link>
                  </div>
                );
              })}
            </div>
          </div>
        );
      },
    },
    {
      title: '帖子',
      dataIndex: 'post_count',
      width: 88,
      align: 'right',
      search: false,
      sorter: (left, right) => (left.post_count ?? 0) - (right.post_count ?? 0),
      key: 'posts',
      sortOrder: tableSortOrder(tableSort, 'posts'),
      render: (_, project) => (
        <span className="projects-page__count">{formatNumber(project.post_count)}</span>
      ),
    },
    {
      title: '作者',
      dataIndex: 'author_count',
      width: 88,
      align: 'right',
      search: false,
      sorter: (left, right) => (left.author_count ?? 0) - (right.author_count ?? 0),
      key: 'authors',
      sortOrder: tableSortOrder(tableSort, 'authors'),
      render: (_, project) => (
        <span className="projects-page__count">{formatNumber(project.author_count)}</span>
      ),
    },
    {
      title: '最近更新',
      dataIndex: 'updated_at',
      width: 180,
      valueType: 'dateTime',
      search: false,
      sorter: (left, right) => left.updated_at.localeCompare(right.updated_at),
      key: 'updated',
      sortOrder: tableSortOrder(tableSort, 'updated'),
      render: (_, project) => formatDate(project.updated_at),
    },
    {
      title: '操作',
      valueType: 'option',
      key: 'option',
      width: 144,
      fixed: 'right',
      render: (_, project) => {
        return [
          <Link key="open" to={`/projects/${project.id}`}>
            查看
          </Link>,
          <Dropdown
            key="more"
            trigger={['click']}
            menu={{
              items: [
                {
                  key: 'edit',
                  label: '编辑项目',
                  onClick: () => setEditingProject(project),
                },
                {
                  key: 'delete',
                  label: '删除项目',
                  danger: true,
                  disabled:
                    taskStateUnknown || project.active_tasks.length > 0 || removeProject.isPending,
                  onClick: () => setDeletingProject(project),
                },
              ],
            }}
          >
            <Button type="link" size="small" icon={<EllipsisOutlined />}>
              更多
            </Button>
          </Dropdown>,
        ];
      },
    },
  ];

  return (
    <PageContainer
      title="调研项目"
      subTitle="集中管理项目资产与正在执行的任务"
    >
      <div className="projects-page">
        {hasBackgroundError ? (
          <Alert
            showIcon
            type="warning"
            title="部分数据暂时无法刷新"
            description="当前继续显示上次成功获取的数据，列表会自动重试。"
            action={
              <Button size="small" onClick={refreshProjects}>
                立即重试
              </Button>
            }
          />
        ) : null}

        {hasInitialError ? (
          <QueryError error={projectsQuery.error} retry={() => void projectsQuery.refetch()} />
        ) : (
          <ProTable<ProjectTaskRow, ProjectSearchParams>
            actionRef={actionRef}
            rowKey="id"
            columns={columns}
            loading={projectsQuery.isLoading || (tasksQuery.isLoading && !tasksQuery.data)}
            params={{ ...filters, refreshToken }}
            request={async (params) => {
              const filteredRows = sortProjectRows(
                filterProjectTaskRows(projectRowsRef.current, params),
                tableSort,
              );
              const current = params.current ?? 1;
              const pageSize = params.pageSize ?? 10;
              const start = (current - 1) * pageSize;
              return {
                data: filteredRows.slice(start, start + pageSize),
                total: filteredRows.length,
                success: true,
              };
            }}
            onChange={(_, __, sorter, extra) => {
              if (extra.action !== 'sort' || Array.isArray(sorter)) return;
              setTableSort(
                tableSortFromChange(
                  sorter.columnKey ?? sorter.field,
                  sorter.order,
                  PROJECT_TABLE_SORTS,
                  'default',
                ),
              );
            }}
            search={false}
            pagination={{
              defaultPageSize: 10,
              showSizeChanger: true,
              showQuickJumper: true,
              showTotal: (total) => `共 ${total} 个项目`,
            }}
            options={false}
            scroll={{ x: 960 }}
            toolbar={{
              title: (
                <span className="projects-page__summary">
                  共 <strong>{projectRows.length}</strong> 个项目 · <strong>{activeCount}</strong>{' '}
                  个活跃任务
                </span>
              ),
              subTitle:
                refreshing ? (
                  <span className="projects-page__refreshing" role="status">
                    正在更新列表…
                  </span>
                ) : undefined,
              actions: [
                <section
                  key="project-list-toolbar"
                  className="projects-page__toolbar"
                  aria-label="项目列表查询与操作"
                >
                  <Input.Search
                    allowClear
                    className="projects-page__search"
                    aria-label="搜索项目名称或说明"
                    placeholder="搜索项目名称或说明"
                    value={filters.name ?? ''}
                    onChange={(event) =>
                      setFilters((current) => ({
                        ...current,
                        name: event.target.value || undefined,
                      }))
                    }
                  />
                  <Select<TaskStatusFilterValue>
                    className="projects-page__filter"
                    aria-label="按任务状态筛选"
                    value={filters.task_status ?? 'all'}
                    options={[
                      { value: 'all', label: '全部任务状态' },
                      ...Object.entries(taskStatusValueEnum).map(([value, { text }]) => ({
                        value: value as ProjectTaskStatusFilter,
                        label: text,
                      })),
                    ]}
                    onChange={(value) =>
                      setFilters((current) => ({
                        ...current,
                        task_status: value === 'all' ? undefined : value,
                      }))
                    }
                  />
                  <Button
                    className="projects-page__refresh-action"
                    icon={<ReloadOutlined />}
                    loading={refreshing}
                    onClick={refreshProjects}
                  >
                    刷新
                  </Button>
                  <Button
                    className="projects-page__create-action"
                    type="primary"
                    icon={<PlusOutlined />}
                    onClick={() => history.push('/projects/new')}
                  >
                    新建项目
                  </Button>
                </section>,
              ],
            }}
            locale={{
              emptyText: (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={
                    projectRows.length === 0 ? '还没有调研项目' : '没有符合当前筛选条件的项目'
                  }
                >
                  {projectRows.length === 0 ? (
                    <Button type="primary" onClick={() => history.push('/projects/new')}>
                      创建第一个项目
                    </Button>
                  ) : null}
                </Empty>
              ),
            }}
          />
        )}
      </div>
      <ProjectEditModal
        project={editingProject}
        open={Boolean(editingProject)}
        saving={updateProject.isPending}
        onCancel={() => {
          if (!updateProject.isPending) setEditingProject(undefined);
        }}
        onSave={(values) => {
          if (!editingProject) return;
          updateProject.mutate({ projectId: editingProject.id, values });
        }}
      />
      {deletingProject ? (
        <ProjectDeleteAction
          project={deletingProject}
          taskStateUnknown={taskStateUnknown}
          mutationPending={removeProject.isPending}
          deleting={
            removeProject.isPending && removeProject.variables?.id === deletingProject.id
          }
          open
          hideTrigger
          onOpenChange={(open) => {
            if (!open && !removeProject.isPending) setDeletingProject(undefined);
          }}
          onDelete={() => removeProject.mutate(deletingProject)}
        />
      ) : null}
    </PageContainer>
  );
}
