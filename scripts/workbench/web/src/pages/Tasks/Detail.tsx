import {
  ArrowLeftOutlined,
  ClockCircleOutlined,
  RedoOutlined,
  SafetyCertificateOutlined,
  StopOutlined,
} from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { history, Link, useParams } from '@umijs/max';
import type { TimelineItemProps } from 'antd';
import {
  Alert,
  App,
  Button,
  Card,
  Collapse,
  Descriptions,
  Empty,
  Popconfirm,
  Segmented,
  Space,
  Timeline,
  Typography,
} from 'antd';
import { useEffect, useRef, useState } from 'react';
import { QueryError, QueryLoading } from '@/components/QueryState';
import TaskProgress from '@/components/TaskProgress';
import TaskStatusTag from '@/components/TaskStatusTag';
import { taskInputPresentation } from '@/features/tasks/taskInputPresentation';
import { apiService } from '@/services/api';
import { queryKeys } from '@/services/queryKeys';
import type { TaskEvent, TaskStatus } from '@/types';
import {
  activeTaskStatuses,
  formatDate,
  researchTypeLabels,
  taskPhaseLabels,
  taskTypeLabels,
} from '@/utils/format';
import { didTaskSettle } from '@/utils/taskPolling';
import { taskEventWarnings } from '@/utils/taskEvents';
import './index.css';

const retryableStatuses = new Set<TaskStatus>(['failed', 'partial']);
type TimelineOrder = 'newest' | 'oldest';

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '操作失败，请稍后重试';
}

function eventColor(event: TaskEvent): TimelineItemProps['color'] {
  const marker = `${event.event_type} ${event.phase}`.toLocaleLowerCase('zh-CN');
  if (marker.includes('fail') || marker.includes('error')) return 'red';
  if (marker.includes('warning') || marker.includes('waiting')) return 'orange';
  if (marker.includes('complete') || marker.includes('success')) return 'green';
  return 'blue';
}

export default function TaskDetailPage() {
  const { id: routeTaskId = '', projectId, taskId } =
    useParams<{ id?: string; projectId?: string; taskId?: string }>();
  const id = taskId ?? routeTaskId;
  const projectContextId = projectId && /^\d+$/.test(projectId) ? projectId : undefined;
  const taskListPath = projectContextId ? `/projects/${projectContextId}/tasks` : '/tasks';
  const buildTaskDetailPath = (nextTaskId: string) =>
    projectContextId ? `/projects/${projectContextId}/tasks/${nextTaskId}` : `/tasks/${nextTaskId}`;
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const previousTask = useRef<{ id: string; status: TaskStatus } | undefined>(undefined);
  const [timelineOrder, setTimelineOrder] = useState<TimelineOrder>('newest');

  const task = useQuery({
    queryKey: queryKeys.task(id),
    queryFn: ({ signal }) => apiService.task(id, signal),
    enabled: Boolean(id),
    refetchInterval: (query) =>
      query.state.data && activeTaskStatuses.has(query.state.data.status) ? 1_500 : false,
  });

  const events = useQuery({
    queryKey: queryKeys.taskEvents(id),
    queryFn: ({ signal }) => apiService.taskEvents(id, 0, signal),
    enabled: Boolean(id) && Boolean(task.data),
    placeholderData: (previous) => previous,
    refetchInterval: task.data && activeTaskStatuses.has(task.data.status) ? 1_500 : false,
  });

  useEffect(() => {
    if (!task.data) return;
    const previousStatus = previousTask.current?.id === id ? previousTask.current.status : undefined;
    const shouldFinalSync = didTaskSettle(previousStatus, task.data.status);
    previousTask.current = { id, status: task.data.status };
    if (!shouldFinalSync) return;

    void queryClient.invalidateQueries({ queryKey: queryKeys.taskEvents(id), exact: true });
  }, [id, queryClient, task.data]);

  const cancelTask = useMutation({
    mutationFn: () => apiService.cancelTask(id),
    onSuccess: async () => {
      message.success('任务已取消');
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.tasks }),
        queryClient.invalidateQueries({ queryKey: queryKeys.task(id) }),
      ]);
      history.push(taskListPath);
    },
    onError: (error) => message.error(errorMessage(error)),
  });

  const retryTask = useMutation({
    mutationFn: () => apiService.retryTask(id),
    onSuccess: async (nextTask) => {
      message.success('已创建重试任务');
      await queryClient.invalidateQueries({ queryKey: queryKeys.tasks });
      history.push(buildTaskDetailPath(nextTask.id));
    },
    onError: (error) => message.error(errorMessage(error)),
  });

  const resumeTask = useMutation({
    mutationFn: () => apiService.resumeTask(id),
    onSuccess: async () => {
      message.success('已通知任务继续执行');
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.task(id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.taskEvents(id), exact: true }),
      ]);
    },
    onError: (error) => message.error(errorMessage(error)),
  });

  if (task.isPending) {
    return (
      <PageContainer title="任务详情" onBack={() => history.push(taskListPath)}>
        <Card>
          <QueryLoading rows={6} />
        </Card>
      </PageContainer>
    );
  }

  if (task.isError || !task.data) {
    return (
      <PageContainer title="任务详情" onBack={() => history.push(taskListPath)}>
        <QueryError error={task.error} retry={() => void task.refetch()} />
      </PageContainer>
    );
  }

  const value = task.data;
  const cancellable = activeTaskStatuses.has(value.status);
  const retryable = retryableStatuses.has(value.status);
  const inputPresentation = taskInputPresentation(value);
  const timelineItems = (events.data ?? []).map((event) => {
    const warnings = taskEventWarnings(event.payload_json);
    return {
      key: event.id,
      color: eventColor(event),
      label: formatDate(event.created_at, true),
      children: (
        <div className="task-detail-event">
          <div className="task-detail-event-title">
            <Typography.Text strong>{taskPhaseLabels[event.phase] ?? event.phase}</Typography.Text>
            <span className="task-detail-event-type">{event.event_type}</span>
          </div>
          <Typography.Text type="secondary">
            {event.payload_json.message ||
              (warnings.length ? `${warnings.length} 条执行告警` : event.event_type)}
          </Typography.Text>
          {warnings.length ? (
            <Alert
              className="task-detail-event-warnings"
              type="warning"
              showIcon
              title="执行告警"
              description={
                <ul>
                  {warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              }
            />
          ) : null}
        </div>
      ),
    };
  });
  const orderedTimelineItems =
    timelineOrder === 'newest' ? [...timelineItems].reverse() : timelineItems;

  return (
    <PageContainer
      title={`${taskTypeLabels[value.task_type]}任务`}
      subTitle={value.id}
      tags={<TaskStatusTag status={value.status} />}
      onBack={() => history.push(taskListPath)}
      backIcon={<ArrowLeftOutlined />}
      content="任务运行期间会在后台更新当前进度和执行轨迹，不会打断正在查看的内容。"
      extra={[
        value.status === 'waiting_login' ? (
          <Button
            key="resume"
            type="primary"
            loading={resumeTask.isPending}
            disabled={cancelTask.isPending}
            icon={<SafetyCertificateOutlined />}
            onClick={() => resumeTask.mutate()}
          >
            已完成验证，继续任务
          </Button>
        ) : null,
        cancellable ? (
          <Popconfirm
            key="cancel"
            title="取消当前任务？"
            description={
              projectContextId
                ? '已完成的采集结果会保留，取消后返回项目任务列表。'
                : '已完成的采集结果会保留，取消后返回任务中心。'
            }
            okText="取消任务"
            cancelText="继续运行"
            okButtonProps={{ danger: true, loading: cancelTask.isPending }}
            onConfirm={() => cancelTask.mutateAsync()}
          >
            <Button
              danger
              loading={cancelTask.isPending}
              disabled={resumeTask.isPending}
              icon={<StopOutlined />}
            >
              取消任务
            </Button>
          </Popconfirm>
        ) : null,
        retryable ? (
          <Button
            key="retry"
            type="primary"
            loading={retryTask.isPending}
            icon={<RedoOutlined />}
            onClick={() => retryTask.mutate()}
          >
            重试任务
          </Button>
        ) : null,
      ].filter(Boolean)}
    >
      <div className="task-detail-stack">
        {value.status === 'waiting_login' ? (
          <Alert
            type="warning"
            showIcon
            title="等待人工登录或验证"
            description="请为当前数据采集 CLI 完成小红书登录、验证码或安全验证。完成后点击“已完成验证，继续任务”；系统也会定时检测，并从当前来源继续，无需重新创建任务。"
          />
        ) : null}

        {value.error_message ? (
          <Alert
            type={value.status === 'failed' ? 'error' : 'warning'}
            showIcon
            title={value.status === 'failed' ? '任务执行失败' : '任务执行提示'}
            description={value.error_message}
          />
        ) : null}

        <Card className="task-detail-summary">
          <div className="task-detail-summary-main">
            <div>
              <Space size="small">
                <TaskStatusTag status={value.status} />
                <Typography.Text type="secondary">当前阶段</Typography.Text>
              </Space>
              <Typography.Title level={3} className="task-detail-phase">
                {taskPhaseLabels[value.current_phase] ?? value.current_phase ?? '正在准备任务'}
              </Typography.Title>
            </div>
            <div className="task-detail-progress">
              <TaskProgress task={value} />
            </div>
          </div>
        </Card>

        <Card title="任务信息">
          <Descriptions
            bordered
            size="small"
            column={{ xs: 1, sm: 1, md: 2, lg: 3 }}
            items={[
              {
                key: 'id',
                label: '任务 ID',
                children: (
                  <Typography.Text copyable={{ text: value.id }}>{value.id}</Typography.Text>
                ),
              },
              {
                key: 'project',
                label: value.post_id ? '所属帖子' : value.author_id ? '所属作者' : '所属项目',
                children: value.post_id ? (
                  <Link to={`/posts/${value.post_id}`}>帖子 #{value.post_id}</Link>
                ) : value.author_id ? (
                  <Link to={`/authors/${value.author_id}/${value.task_type === 'vision' ? 'posts' : 'reports'}`}>
                    作者 #{value.author_id}
                  </Link>
                ) : value.project_id === null ? (
                  <Typography.Text type="secondary">独立任务</Typography.Text>
                ) : (
                  <Link to={`/projects/${value.project_id}/tasks`}>
                    项目 #{value.project_id}
                  </Link>
                ),
              },
              { key: 'source', label: '创建来源', children: value.created_from || '—' },
              { key: 'created', label: '创建时间', children: formatDate(value.created_at, true) },
              { key: 'started', label: '开始时间', children: formatDate(value.started_at, true) },
              { key: 'finished', label: '完成时间', children: formatDate(value.finished_at, true) },
              {
                key: 'warnings',
                label: '告警数量',
                children: value.warning_count.toLocaleString('zh-CN'),
              },
              {
                key: 'mode',
                label: '执行范围',
                children: value.mode === 'post' ? '单条帖子' : researchTypeLabels[value.mode],
              },
              {
                key: 'collector',
                label: '能力调度',
                children: value.task_type === 'research' || value.task_type === 'comments'
                  ? '按原子能力自动选择'
                  : '—',
              },
              { key: 'phase', label: '阶段标识', children: value.current_phase || '—' },
            ]}
          />
        </Card>

        <Card title="创建参数" extra={<Typography.Text type="secondary">任务启动时提交的配置</Typography.Text>}>
          {inputPresentation.sections.length ? (
            <div className="task-detail-input-sections">
              {inputPresentation.sections.map((section) => (
                <section className="task-detail-input-section" key={section.key}>
                  <Typography.Title level={5}>{section.title}</Typography.Title>
                  <Descriptions
                    bordered
                    size="small"
                    column={{ xs: 1, sm: 1, md: 2 }}
                    items={section.items.map((entry) => ({
                      key: entry.key,
                      label: entry.label,
                      children: (
                        <Typography.Text className="task-detail-input-value">
                          {entry.value}
                        </Typography.Text>
                      ),
                    }))}
                  />
                </section>
              ))}
            </div>
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未记录可展示的创建参数" />
          )}
          <Collapse
            className="task-detail-input-raw"
            size="small"
            ghost
            items={[
              {
                key: 'raw',
                label: '查看原始参数 JSON',
                children: (
                  <pre className="task-detail-input-json">{inputPresentation.rawJson}</pre>
                ),
              },
            ]}
          />
        </Card>

        <Card
          title="执行轨迹"
          extra={
            <Space size="small" wrap>
              <Typography.Text type="secondary">共 {timelineItems.length} 条事件</Typography.Text>
              {cancellable ? (
                <Typography.Text type="secondary">
                  <ClockCircleOutlined /> 自动刷新中
                </Typography.Text>
              ) : null}
              <Segmented<TimelineOrder>
                size="small"
                aria-label="执行轨迹排列顺序"
                value={timelineOrder}
                options={[
                  { label: '最新在前', value: 'newest' },
                  { label: '最早在前', value: 'oldest' },
                ]}
                onChange={setTimelineOrder}
              />
            </Space>
          }
        >
          {events.isError && !events.data ? (
            <QueryError error={events.error} retry={() => void events.refetch()} />
          ) : events.isPending ? (
            <QueryLoading rows={4} />
          ) : timelineItems.length ? (
            <div className="task-detail-timeline-scroll">
              <Timeline
                className="task-detail-timeline"
                mode="left"
                items={orderedTimelineItems}
              />
            </div>
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="任务尚未产生执行事件" />
          )}
        </Card>
      </div>
    </PageContainer>
  );
}
