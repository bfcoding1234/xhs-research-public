import { EyeOutlined, ReloadOutlined, StopOutlined } from '@ant-design/icons';
import type { ProColumns } from '@ant-design/pro-components';
import { ProTable } from '@ant-design/pro-components';
import { Button, Popconfirm, Space, Typography } from 'antd';
import TaskProgress from '@/components/TaskProgress';
import TaskStatusTag from '@/components/TaskStatusTag';
import {
  tableSortFromChange,
  tableSortOrder,
  useListSort,
} from '@/features/preferences/listSortPreferences';
import { TABLE_COLUMN_PREFERENCES } from '@/features/preferences/tableColumnPreferences';
import type { Task } from '@/types';
import {
  activeTaskStatuses,
  formatDate,
  formatTaskDuration,
  taskDurationMs,
  taskPhaseLabels,
  taskTypeLabels,
} from '@/utils/format';

const PROJECT_TASK_TABLE_SORTS = [
  'duration:asc',
  'duration:desc',
  'created:asc',
  'created:desc',
] as const;

export default function ProjectTasksTable({
  tasks,
  onView,
  onCancel,
  onRetry,
  pendingTaskId,
}: {
  tasks: Task[];
  onView: (id: string) => void;
  onCancel: (id: string) => void;
  onRetry: (id: string) => void;
  pendingTaskId?: string;
}) {
  const [tableSort, setTableSort] = useListSort(
    'tasks.project',
    PROJECT_TASK_TABLE_SORTS,
    'created:desc',
  );
  const columns: ProColumns<Task>[] = [
    {
      title: '任务',
      dataIndex: 'id',
      width: 240,
      fixed: 'left',
      render: (_, row) => (
        <Space orientation="vertical" size={0}>
          <Button type="link" style={{ padding: 0 }} onClick={() => onView(row.id)}>
            {taskTypeLabels[row.task_type]}
          </Button>
          <Typography.Text type="secondary" className="mono">
            {row.id}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: '入口',
      dataIndex: 'created_from',
      width: 100,
      renderText: (value) => value || '—',
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (_, row) => <TaskStatusTag status={row.status} />,
    },
    {
      title: '阶段',
      dataIndex: 'current_phase',
      width: 150,
      renderText: (value) => taskPhaseLabels[value] || value || '等待开始',
    },
    {
      title: '进度',
      key: 'progress',
      width: 180,
      render: (_, row) => <TaskProgress task={row} compact />,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 180,
      renderText: (value: string) => formatDate(value),
      sorter: (left, right) => Date.parse(left.created_at) - Date.parse(right.created_at),
      key: 'created',
      sortOrder: tableSortOrder(tableSort, 'created'),
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
      title: '操作',
      valueType: 'option',
      width: 180,
      fixed: 'right',
      render: (_, row) => {
        const actions = [
          <Button key="view" type="link" icon={<EyeOutlined />} onClick={() => onView(row.id)}>
            查看
          </Button>,
        ];
        if (activeTaskStatuses.has(row.status)) {
          actions.push(
            <Popconfirm
              key="cancel"
              title="取消当前任务？"
              description="已经采集的数据会保留。"
              okText="取消任务"
              cancelText="继续运行"
              onConfirm={() => onCancel(row.id)}
            >
              <Button type="link" danger icon={<StopOutlined />} loading={pendingTaskId === row.id}>
                取消
              </Button>
            </Popconfirm>,
          );
        }
        if (row.status === 'failed' || row.status === 'partial') {
          actions.push(
            <Button
              key="retry"
              type="link"
              icon={<ReloadOutlined />}
              loading={pendingTaskId === row.id}
              onClick={() => onRetry(row.id)}
            >
              重试
            </Button>,
          );
        }
        return actions;
      },
    },
  ];
  return (
    <ProTable<Task>
      rowKey="id"
      headerTitle={`任务记录（${tasks.length}）`}
      columns={columns}
      dataSource={tasks}
      search={false}
      onChange={(_, __, sorter, extra) => {
        if (extra.action !== 'sort' || Array.isArray(sorter)) return;
        setTableSort(
          tableSortFromChange(
            sorter.columnKey ?? sorter.field,
            sorter.order,
            PROJECT_TASK_TABLE_SORTS,
            'created:desc',
          ),
        );
      }}
      scroll={{ x: 1220 }}
      pagination={{ defaultPageSize: 20, showSizeChanger: true, showTotal: (total) => `共 ${total} 个` }}
      options={{ reload: false, density: true, setting: true, fullScreen: true }}
      columnsState={TABLE_COLUMN_PREFERENCES.projectTasks}
    />
  );
}
