import {
  ArrowRightOutlined,
  FileSearchOutlined,
  FundProjectionScreenOutlined,
  PlusOutlined,
  ProjectOutlined,
  SettingOutlined,
  StopOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import { PageContainer, ProCard, StatisticCard } from '@ant-design/pro-components';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { history, Link } from '@umijs/max';
import {
  Alert,
  Badge,
  Button,
  Empty,
  List,
  message,
  Popconfirm,
  Progress,
  Skeleton,
  Space,
  Tag,
  Typography,
} from 'antd';
import type { ReactNode } from 'react';
import { QueryError } from '@/components/QueryState';
import TaskStatusTag from '@/components/TaskStatusTag';
import { apiService } from '@/services/api';
import { queryKeys } from '@/services/queryKeys';
import type { Project, Task } from '@/types';
import {
  activeTaskStatuses,
  formatBytes,
  formatDate,
  formatNumber,
  researchTypeLabels,
  taskPercent,
  taskPhaseLabels,
  taskTypeLabels,
} from '@/utils/format';
import './index.css';

const { Text } = Typography;

const POLLING_INTERVAL = 5_000;

function projectName(projects: Project[] | undefined, projectId: number | null) {
  if (projectId === null) {
    return '独立任务';
  }
  return projects?.find((project) => project.id === projectId)?.name ?? `项目 #${projectId}`;
}

function hasActiveTask(tasks: Task[] | undefined) {
  return tasks?.some((task) => activeTaskStatuses.has(task.status)) ?? false;
}

function QuickLink({
  to,
  icon,
  title,
  description,
}: {
  to: string;
  icon: ReactNode;
  title: string;
  description: string;
}) {
  return (
    <Link className="overview-page__quick-link" to={to}>
      <span className="overview-page__quick-link-icon" aria-hidden="true">
        {icon}
      </span>
      <span className="overview-page__quick-link-copy">
        <Text strong>{title}</Text>
        <span className="overview-page__quick-link-description">{description}</span>
      </span>
      <ArrowRightOutlined aria-hidden="true" />
    </Link>
  );
}

export default function OverviewPage() {
  const queryClient = useQueryClient();
  const healthQuery = useQuery({
    queryKey: queryKeys.health,
    queryFn: ({ signal }) => apiService.health(signal),
    refetchInterval: 15_000,
    placeholderData: keepPreviousData,
  });
  const statsQuery = useQuery({
    queryKey: queryKeys.stats,
    queryFn: ({ signal }) => apiService.stats(signal),
    refetchInterval: 15_000,
    placeholderData: keepPreviousData,
  });
  const projectsQuery = useQuery({
    queryKey: queryKeys.projects,
    queryFn: ({ signal }) => apiService.projects(signal),
    refetchInterval: 10_000,
    placeholderData: keepPreviousData,
  });
  const tasksQuery = useQuery({
    queryKey: queryKeys.tasks,
    queryFn: ({ signal }) => apiService.tasks(signal),
    refetchInterval: (query) => (hasActiveTask(query.state.data) ? POLLING_INTERVAL : 15_000),
    placeholderData: keepPreviousData,
  });

  const cancelTask = useMutation({
    mutationFn: apiService.cancelTask,
    onSuccess: async (_, taskId) => {
      message.success('任务已取消');
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.tasks }),
        queryClient.invalidateQueries({ queryKey: queryKeys.projects }),
        queryClient.invalidateQueries({ queryKey: queryKeys.stats }),
        queryClient.invalidateQueries({ queryKey: queryKeys.task(taskId) }),
      ]);
    },
    onError: (error) => {
      message.error(error instanceof Error ? error.message : '取消任务失败');
    },
  });

  const activeTasks = (tasksQuery.data ?? [])
    .filter((task) => activeTaskStatuses.has(task.status))
    .sort((left, right) => right.created_at.localeCompare(left.created_at));
  const recentProjects = (projectsQuery.data ?? []).slice(0, 5);
  const backgroundErrors = [
    healthQuery.data && healthQuery.error ? '服务状态' : null,
    statsQuery.data && statsQuery.error ? '统计数据' : null,
    projectsQuery.data && projectsQuery.error ? '项目列表' : null,
    tasksQuery.data && tasksQuery.error ? '任务列表' : null,
  ].filter(Boolean);

  return (
    <PageContainer
      className="overview-page"
      title="工作台总览"
      subTitle="查看调研资产、运行进度与本地服务状态"
      extra={[
        <Button key="projects" onClick={() => history.push('/projects')}>
          查看项目
        </Button>,
        <Button
          key="create"
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => history.push('/projects/new')}
        >
          新建调研
        </Button>,
      ]}
    >
      <div className="overview-page">
        {backgroundErrors.length > 0 ? (
          <Alert
            showIcon
            type="warning"
            title={`${backgroundErrors.join('、')}暂时无法刷新`}
            description="当前继续显示上次成功获取的数据，工作台会自动重试。"
            action={
              <Button
                size="small"
                onClick={() => {
                  void Promise.all([
                    healthQuery.refetch(),
                    statsQuery.refetch(),
                    projectsQuery.refetch(),
                    tasksQuery.refetch(),
                  ]);
                }}
              >
                立即重试
              </Button>
            }
          />
        ) : null}

        <ProCard className="overview-page__pulse" styles={{ body: { paddingBlock: 16 } }}>
          <div className="overview-page__pulse-content">
            <div className="overview-page__pulse-copy">
              <Space size={10} wrap>
                <Badge
                  status={
                    healthQuery.data ? 'success' : healthQuery.isLoading ? 'processing' : 'error'
                  }
                  text={
                    healthQuery.data
                      ? '本地服务运行正常'
                      : healthQuery.isLoading
                        ? '正在连接本地服务'
                        : '本地服务连接失败'
                  }
                />
                {healthQuery.data ? <Tag>v{healthQuery.data.version}</Tag> : null}
              </Space>
              <Text type="secondary">
                {activeTasks.length > 0
                  ? `${activeTasks.length} 个任务正在处理，页面会自动刷新进度。`
                  : '当前没有运行中的任务，可以开始一次新的调研。'}
              </Text>
            </div>
            <div className="overview-page__pulse-meta">
              <span>
                数据库{' '}
                <span className="overview-page__pulse-value">
                  {statsQuery.data ? formatBytes(statsQuery.data.database_bytes) : '—'}
                </span>
              </span>
              <span>
                本地媒体{' '}
                <span className="overview-page__pulse-value">
                  {statsQuery.data ? formatBytes(statsQuery.data.media_bytes) : '—'}
                </span>
              </span>
            </div>
          </div>
        </ProCard>

        {statsQuery.isLoading ? (
          <ProCard>
            <Skeleton active paragraph={{ rows: 2 }} />
          </ProCard>
        ) : statsQuery.isError && !statsQuery.data ? (
          <QueryError error={statsQuery.error} retry={() => void statsQuery.refetch()} />
        ) : (
          <div className="stat-grid">
            <StatisticCard
              statistic={{
                title: '调研项目',
                value: statsQuery.data?.projects ?? 0,
                prefix: <ProjectOutlined />,
              }}
            />
            <StatisticCard
              statistic={{
                title: '证据帖子',
                value: statsQuery.data?.global_posts ?? 0,
                prefix: <FileSearchOutlined />,
              }}
            />
            <StatisticCard
              statistic={{
                title: '关联作者',
                value: statsQuery.data?.global_authors ?? 0,
                prefix: <TeamOutlined />,
              }}
            />
            <StatisticCard
              statistic={{
                title: '研究报告',
                value: statsQuery.data?.reports ?? 0,
                prefix: <FundProjectionScreenOutlined />,
              }}
            />
          </div>
        )}

        <div className="overview-page__main-grid">
          <ProCard title="活跃任务" extra={<Link to="/tasks">进入任务中心</Link>} headerBordered>
            {tasksQuery.isLoading && !tasksQuery.data ? (
              <Skeleton active paragraph={{ rows: 5 }} />
            ) : tasksQuery.isError && !tasksQuery.data ? (
              <QueryError error={tasksQuery.error} retry={() => void tasksQuery.refetch()} />
            ) : activeTasks.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无活跃任务">
                <Button type="primary" onClick={() => history.push('/tasks/new')}>
                  发起采集任务
                </Button>
              </Empty>
            ) : (
              <List
                className="overview-page__task-list"
                dataSource={activeTasks}
                renderItem={(task) => {
                  const percent = taskPercent(task);
                  return (
                    <List.Item
                      key={task.id}
                      actions={[
                        <Link key="detail" to={`/tasks/${task.id}`}>
                          查看详情
                        </Link>,
                        <Popconfirm
                          key="cancel"
                          title="取消这个任务？"
                          description="已采集的数据会保留，但任务无法继续运行。"
                          okText="取消任务"
                          cancelText="继续运行"
                          okButtonProps={{ danger: true }}
                          onConfirm={() => cancelTask.mutate(task.id)}
                        >
                          <Button
                            type="link"
                            danger
                            size="small"
                            icon={<StopOutlined />}
                            loading={cancelTask.isPending && cancelTask.variables === task.id}
                            aria-label={`取消任务：${projectName(projectsQuery.data, task.project_id)}`}
                          >
                            取消
                          </Button>
                        </Popconfirm>,
                      ]}
                    >
                      <div className="overview-page__task-main">
                        <div className="overview-page__task-heading">
                          <Link to={`/tasks/${task.id}`}>
                            <Text strong>{projectName(projectsQuery.data, task.project_id)}</Text>
                          </Link>
                          <TaskStatusTag status={task.status} />
                          <Text type="secondary">{taskTypeLabels[task.task_type]}</Text>
                        </div>
                        <div className="overview-page__task-progress">
                          <Progress
                            percent={percent}
                            size="small"
                            status={task.status === 'waiting_login' ? 'exception' : 'active'}
                            aria-label={`${projectName(projectsQuery.data, task.project_id)}进度 ${percent}%`}
                          />
                          <Text type="secondary">
                            {taskPhaseLabels[task.current_phase] ??
                              task.current_phase ??
                              '准备任务'}
                          </Text>
                        </div>
                      </div>
                    </List.Item>
                  );
                }}
              />
            )}
          </ProCard>

          <ProCard title="快速入口" headerBordered>
            <div className="overview-page__quick-links">
              <QuickLink
                to="/projects/new"
                icon={<PlusOutlined />}
                title="新建调研"
                description="从关键词、作者或混合模式开始"
              />
              <QuickLink
                to="/projects"
                icon={<ProjectOutlined />}
                title="管理项目"
                description="筛选项目并继续已有研究"
              />
              <QuickLink
                to="/tasks"
                icon={<FundProjectionScreenOutlined />}
                title="任务中心"
                description="查看执行阶段、告警与失败原因"
              />
              <QuickLink
                to="/settings"
                icon={<SettingOutlined />}
                title="后台配置"
                description="调整采集、图片理解与报告参数"
              />
            </div>
          </ProCard>
        </div>

        <ProCard title="最近项目" extra={<Link to="/projects">查看全部项目</Link>} headerBordered>
          {projectsQuery.isLoading && !projectsQuery.data ? (
            <Skeleton active paragraph={{ rows: 5 }} />
          ) : projectsQuery.isError && !projectsQuery.data ? (
            <QueryError error={projectsQuery.error} retry={() => void projectsQuery.refetch()} />
          ) : recentProjects.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有调研项目">
              <Button type="primary" onClick={() => history.push('/projects/new')}>
                创建第一个项目
              </Button>
            </Empty>
          ) : (
            <List
              dataSource={recentProjects}
              renderItem={(project) => (
                <List.Item
                  key={project.id}
                  actions={[
                    <Link key="open" to={`/projects/${project.id}`}>
                      打开项目
                    </Link>,
                  ]}
                >
                  <List.Item.Meta
                    avatar={<ProjectOutlined aria-hidden="true" />}
                    title={
                      <Space size={8} wrap>
                        <Link to={`/projects/${project.id}`}>{project.name}</Link>
                        <Tag>{researchTypeLabels[project.research_type]}</Tag>
                        <TaskStatusTag status={project.latest_task_status} />
                      </Space>
                    }
                    description={
                      <Space size={[12, 4]} wrap>
                        <Text
                          className="overview-page__recent-project-description"
                          type="secondary"
                          ellipsis
                        >
                          {project.description || '暂无项目说明'}
                        </Text>
                        <Text type="secondary">{formatNumber(project.post_count)} 篇帖子</Text>
                        <Text type="secondary">{formatNumber(project.author_count)} 位作者</Text>
                        <Text type="secondary">更新于 {formatDate(project.updated_at)}</Text>
                      </Space>
                    }
                  />
                </List.Item>
              )}
            />
          )}
        </ProCard>
      </div>
    </PageContainer>
  );
}
