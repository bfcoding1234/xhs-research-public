import { EyeOutlined, PlusOutlined, RedoOutlined, ReloadOutlined, StopOutlined } from '@ant-design/icons';
import type { ProColumns } from '@ant-design/pro-components';
import { PageContainer, ProTable } from '@ant-design/pro-components';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { history, Link } from '@umijs/max';
import { App, Button, Grid, Input, Popconfirm, Select, Space, Tabs, Typography } from 'antd';
import { useMemo, useState } from 'react';
import { QueryError } from '@/components/QueryState';
import TaskProgress from '@/components/TaskProgress';
import TaskStatusTag from '@/components/TaskStatusTag';
import {
  tableSortFromChange,
  tableSortOrder,
  useListSort,
} from '@/features/preferences/listSortPreferences';
import { TABLE_COLUMN_PREFERENCES } from '@/features/preferences/tableColumnPreferences';
import { apiService } from '@/services/api';
import { queryKeys } from '@/services/queryKeys';
import type { Task, TaskStatus, TaskType } from '@/types';
import {
  activeTaskStatuses,
  formatDate,
  formatTaskDuration,
  taskDurationMs,
  taskPercent,
  taskPhaseLabels,
  taskStatusLabels,
  taskTypeLabels,
} from '@/utils/format';
import './index.css';

type FilterValue<T extends string> = T | 'all';
type TaskTypeFilter = TaskType | 'all';

interface TaskFilters {
  keyword: string;
  status: FilterValue<Exclude<TaskStatus, 'cancelled'>>;
}

const retryableStatuses = new Set<TaskStatus>(['failed', 'partial']);
const taskTypeTabs: Array<{ key: TaskTypeFilter; label: string }> = [
  { key: 'all', label: '全部任务' },
  { key: 'research', label: '采集任务' },
  { key: 'vision', label: '图片理解' },
  { key: 'ai_report', label: '大模型报告' },
  { key: 'keyword_suggestions', label: 'AI 关键词生成' },
  { key: 'comments', label: '评论采集' },
];
const visibleTaskStatusEntries = Object.entries(taskStatusLabels).filter(
  ([value]) => value !== 'cancelled',
);
const TASK_TABLE_SORTS = [
  'progress:asc',
  'progress:desc',
  'warnings:asc',
  'warnings:desc',
  'duration:asc',
  'duration:desc',
  'created:asc',
  'created:desc',
] as const;

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '操作失败，请稍后重试';
}

function taskRelationFilterValue(task: Task): string {
  if (task.post_id) return `post:${task.post_id}`;
  if (task.author_id) return `author:${task.author_id}`;
  if (task.project_id === null) return 'independent';
  return `project:${task.project_id}`;
}

function taskRelationFilterLabel(task: Task, projectNameById: Map<number, string>): string {
  if (task.post_id) return `帖子 #${task.post_id}`;
  if (task.author_id) return `作者 #${task.author_id}`;
  if (task.project_id === null) return '独立任务';
  const projectName = projectNameById.get(task.project_id);
  return projectName ? `${projectName}（项目 #${task.project_id}）` : `项目 #${task.project_id}`;
}

export default function TasksPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const screens = Grid.useBreakpoint();
  const [activeTaskType, setActiveTaskType] = useState<TaskTypeFilter>('all');
  const [filters, setFilters] = useState<TaskFilters>({
    keyword: '',
    status: 'all',
  });
  const [tableSort, setTableSort] = useListSort(
    'tasks.global',
    TASK_TABLE_SORTS,
    'created:desc',
  );

  const tasks = useQuery({
    queryKey: queryKeys.tasks,
    queryFn: ({ signal }) => apiService.tasks(signal),
    refetchInterval: (query) =>
      query.state.data?.some((task) => activeTaskStatuses.has(task.status)) ? 1_500 : false,
  });

  const projects = useQuery({
    queryKey: queryKeys.projects,
    queryFn: ({ signal }) => apiService.projects(signal),
  });

  const projectNameById = useMemo(
    () => new Map((projects.data ?? []).map((project) => [project.id, project.name])),
    [projects.data],
  );

  const relationFilters = useMemo(() => {
    const labels = new Map<string, string>();
    for (const task of tasks.data ?? []) {
      labels.set(
        taskRelationFilterValue(task),
        taskRelationFilterLabel(task, projectNameById),
      );
    }
    return [...labels].map(([value, text]) => ({ value, text })).sort((left, right) =>
      left.text.localeCompare(right.text, 'zh-CN'));
  }, [projectNameById, tasks.data]);

  const phaseFilters = useMemo(() => {
    const phases = new Map(Object.entries(taskPhaseLabels));
    for (const task of tasks.data ?? []) {
      if (!task.current_phase) continue;
      phases.set(task.current_phase, taskPhaseLabels[task.current_phase] ?? task.current_phase);
    }
    return [...phases].map(([value, text]) => ({ value, text })).sort((left, right) =>
      left.text.localeCompare(right.text, 'zh-CN'));
  }, [tasks.data]);

  const cancelTask = useMutation({
    mutationFn: (id: string) => apiService.cancelTask(id),
    onSuccess: async (_result, id) => {
      message.success('任务已取消');
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.tasks }),
        queryClient.invalidateQueries({ queryKey: queryKeys.task(id) }),
      ]);
    },
    onError: (error) => message.error(errorMessage(error)),
  });

  const retryTask = useMutation({
    mutationFn: (id: string) => apiService.retryTask(id),
    onSuccess: async (nextTask) => {
      message.success('已创建重试任务');
      await queryClient.invalidateQueries({ queryKey: queryKeys.tasks });
      history.push(`/tasks/${nextTask.id}`);
    },
    onError: (error) => message.error(errorMessage(error)),
  });

  const filteredTasks = useMemo(() => {
    const normalizedKeyword = filters.keyword.trim().toLocaleLowerCase('zh-CN');
    return (tasks.data ?? []).filter((task) => {
      if (activeTaskType !== 'all' && task.task_type !== activeTaskType) return false;
      if (filters.status !== 'all' && task.status !== filters.status) return false;
      if (!normalizedKeyword) return true;
      return [
        task.id,
        task.author_id ? `作者 ${task.author_id}` : undefined,
        task.post_id ? `帖子 ${task.post_id}` : undefined,
        task.project_id === null ? '独立任务' : String(task.project_id),
        task.project_id === null ? undefined : projectNameById.get(task.project_id),
        task.current_phase,
        task.created_from,
        task.error_message,
        taskTypeLabels[task.task_type],
        taskStatusLabels[task.status],
        taskPhaseLabels[task.current_phase],
      ]
        .filter(Boolean)
        .some((value) => String(value).toLocaleLowerCase('zh-CN').includes(normalizedKeyword));
    });
  }, [activeTaskType, filters, projectNameById, tasks.data]);

  const taskTypeCounts = useMemo(() => {
    const counts: Record<TaskType, number> = {
      research: 0,
      vision: 0,
      ai_report: 0,
      keyword_suggestions: 0,
      comments: 0,
    };
    for (const task of tasks.data ?? []) counts[task.task_type] += 1;
    return counts;
  }, [tasks.data]);
  const activeTaskTypeCount = activeTaskType === 'all'
    ? (tasks.data?.length ?? 0)
    : taskTypeCounts[activeTaskType];
  const activeTaskTypeLabel =
    taskTypeTabs.find((item) => item.key === activeTaskType)?.label ?? '全部任务';

  const columns: ProColumns<Task>[] = [
    {
      title: '任务 ID',
      dataIndex: 'id',
      width: 200,
      fixed: 'left',
      render: (_, task) => (
        <Link className="tasks-page-id" title={task.id} to={`/tasks/${task.id}`}>
          {task.id}
        </Link>
      ),
    },
    {
      title: '关联对象',
      dataIndex: 'project_id',
      width: 160,
      filters: relationFilters,
      filterSearch: true,
      onFilter: (value, task) => taskRelationFilterValue(task) === String(value),
      render: (_, task) => {
        if (task.post_id) {
          return <Link to={`/posts/${task.post_id}`}>帖子 #{task.post_id}</Link>;
        }
        if (task.author_id) {
          const tab = task.task_type === 'vision' ? 'posts' : 'reports';
          return <Link to={`/authors/${task.author_id}/${tab}`}>作者 #{task.author_id}</Link>;
        }
        if (task.project_id === null) {
          return <Typography.Text type="secondary">独立任务</Typography.Text>;
        }
        const projectName = projectNameById.get(task.project_id);
        return (
          <Space orientation="vertical" size={0}>
            <Link
              className="tasks-page-project"
              to={`/projects/${task.project_id}`}
              target="_blank"
              rel="noreferrer"
            >
              {projectName ?? `项目 #${task.project_id}`}
            </Link>
            {projectName ? (
              <Typography.Text type="secondary">项目 #{task.project_id}</Typography.Text>
            ) : null}
          </Space>
        );
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      filters: visibleTaskStatusEntries.map(([value, text]) => ({ value, text })),
      onFilter: (value, task) => task.status === value,
      render: (_, task) => <TaskStatusTag status={task.status} />,
    },
    {
      title: '任务类型',
      dataIndex: 'task_type',
      width: 120,
      filters: taskTypeTabs
        .filter((item): item is { key: TaskType; label: string } => item.key !== 'all')
        .map((item) => ({ value: item.key, text: taskTypeLabels[item.key] })),
      onFilter: (value, task) => task.task_type === value,
      renderText: (value: TaskType) => taskTypeLabels[value] ?? value,
    },
    {
      title: '当前阶段',
      dataIndex: 'current_phase',
      width: 130,
      filters: phaseFilters,
      filterSearch: true,
      onFilter: (value, task) => task.current_phase === value,
      renderText: (value: string) => taskPhaseLabels[value] ?? value ?? '等待开始',
    },
    {
      title: '进度',
      key: 'progress',
      width: 210,
      sorter: (left, right) => taskPercent(left) - taskPercent(right),
      sortOrder: tableSortOrder(tableSort, 'progress'),
      render: (_, task) => (
        <div className="tasks-page-progress">
          <TaskProgress task={task} compact />
          <Typography.Text type="secondary">
            {task.progress_total
              ? `${task.progress_current.toLocaleString('zh-CN')} / ${task.progress_total.toLocaleString('zh-CN')}`
              : `${taskPercent(task)}%`}
          </Typography.Text>
        </div>
      ),
    },
    {
      title: '告警',
      dataIndex: 'warning_count',
      width: 80,
      align: 'right',
      sorter: (left, right) => left.warning_count - right.warning_count,
      key: 'warnings',
      sortOrder: tableSortOrder(tableSort, 'warnings'),
      renderText: (value: number) => value.toLocaleString('zh-CN'),
    },
    {
      title: '耗时',
      key: 'duration',
      width: 120,
      align: 'right',
      sorter: (left, right) => (taskDurationMs(left) ?? -1) - (taskDurationMs(right) ?? -1),
      sortOrder: tableSortOrder(tableSort, 'duration'),
      render: (_, task) => formatTaskDuration(taskDurationMs(task)),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 180,
      sorter: (left, right) =>
        new Date(left.created_at).getTime() - new Date(right.created_at).getTime(),
      key: 'created',
      sortOrder: tableSortOrder(tableSort, 'created'),
      renderText: (value: string) => formatDate(value, true),
    },
    {
      title: '完成时间',
      dataIndex: 'finished_at',
      width: 180,
      renderText: (value?: string | null) => formatDate(value, true),
    },
    {
      title: '操作',
      key: 'actions',
      valueType: 'option',
      width: 160,
      fixed: 'right',
      render: (_, task) => {
        const cancelling = cancelTask.isPending && cancelTask.variables === task.id;
        const retrying = retryTask.isPending && retryTask.variables === task.id;
        return [
          <Button
            key="detail"
            type="link"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => history.push(`/tasks/${task.id}`)}
          >
            详情
          </Button>,
          activeTaskStatuses.has(task.status) ? (
            <Popconfirm
              key="cancel"
              title="取消当前任务？"
              description="已完成的采集结果会保留。"
              okText="取消任务"
              cancelText="继续运行"
              okButtonProps={{ danger: true, loading: cancelling }}
              onConfirm={() => cancelTask.mutateAsync(task.id)}
            >
              <Button danger type="link" size="small" loading={cancelling} icon={<StopOutlined />}>
                取消
              </Button>
            </Popconfirm>
          ) : null,
          retryableStatuses.has(task.status) ? (
            <Button
              key="retry"
              type="link"
              size="small"
              loading={retrying}
              icon={<RedoOutlined />}
              onClick={() => retryTask.mutate(task.id)}
            >
              重试
            </Button>
          ) : null,
        ].filter(Boolean);
      },
    },
  ];

  if (tasks.isError && !tasks.data) {
    return (
      <PageContainer title="任务中心">
        <QueryError error={tasks.error} retry={() => void tasks.refetch()} />
      </PageContainer>
    );
  }

  return (
    <PageContainer
      title="任务中心"
      content="统一查看采集、图片理解和报告任务的执行状态，并在需要时取消或重试。"
      extra={[
        <Button
          key="refresh"
          icon={<ReloadOutlined />}
          loading={tasks.isFetching || projects.isFetching}
          onClick={() => void Promise.all([tasks.refetch(), projects.refetch()])}
        >
          刷新
        </Button>,
      ]}
    >
      <Tabs
        className="tasks-page-tabs"
        activeKey={activeTaskType}
        items={taskTypeTabs.map((item) => ({
          key: item.key,
          label: `${item.label} ${item.key === 'all' ? (tasks.data?.length ?? 0) : taskTypeCounts[item.key]}`,
        }))}
        onChange={(key) => setActiveTaskType(key as TaskTypeFilter)}
      />
      <ProTable<Task>
        key={activeTaskType}
        className="tasks-page-table"
        rowKey="id"
        cardBordered
        loading={tasks.isPending}
        columns={columns}
        dataSource={filteredTasks}
        search={false}
        onChange={(_, __, sorter, extra) => {
          if (extra.action !== 'sort' || Array.isArray(sorter)) return;
          setTableSort(
            tableSortFromChange(
              sorter.columnKey ?? sorter.field,
              sorter.order,
              TASK_TABLE_SORTS,
              'created:desc',
            ),
          );
        }}
        scroll={{ x: 1_730 }}
        pagination={{
          defaultPageSize: 20,
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 个任务`,
        }}
        options={screens.md ? { density: true, setting: true, reload: false } : false}
        columnsState={TABLE_COLUMN_PREFERENCES.globalTasks}
        headerTitle={
          <Space size="small">
            <Typography.Text strong>{activeTaskTypeLabel}</Typography.Text>
            <Typography.Text type="secondary">
              {filteredTasks.length} / {activeTaskTypeCount}
            </Typography.Text>
          </Space>
        }
        toolBarRender={() => {
          const toolbar = [
            <search className="tasks-page-filters" key="filters" aria-label="筛选任务">
              <Input.Search
                allowClear
                className="tasks-page-search"
                placeholder="搜索任务 ID、项目名称、阶段或错误"
                value={filters.keyword}
                onChange={(event) =>
                  setFilters((current) => ({ ...current, keyword: event.target.value }))
                }
              />
              <Select<FilterValue<Exclude<TaskStatus, 'cancelled'>>>
                value={filters.status}
                className="tasks-page-filter"
                aria-label="按任务状态筛选"
                options={[
                  { value: 'all', label: '全部状态' },
                  ...visibleTaskStatusEntries.map(([value, label]) => ({ value, label })),
                ]}
                onChange={(status) => setFilters((current) => ({ ...current, status }))}
              />
            </search>,
          ];
          if (activeTaskType === 'all' || activeTaskType === 'research') {
            toolbar.unshift(
              <Button
                key="create-research-task"
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => history.push('/tasks/new')}
              >
                发起采集任务
              </Button>,
            );
          }
          return toolbar;
        }}
      />
    </PageContainer>
  );
}
