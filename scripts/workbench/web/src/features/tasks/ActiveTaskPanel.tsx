import { LoginOutlined, RightOutlined } from '@ant-design/icons';
import { ProCard } from '@ant-design/pro-components';
import { Button, Flex, Space, Typography } from 'antd';
import TaskProgress from '@/components/TaskProgress';
import TaskStatusTag from '@/components/TaskStatusTag';
import type { Task } from '@/types';
import { taskPhaseLabels, taskTypeLabels } from '@/utils/format';

export default function ActiveTaskPanel({
  tasks,
  onView,
}: {
  tasks: Task[];
  onView: (id: string) => void;
}) {
  if (!tasks.length) return null;
  return (
    <ProCard title="正在执行" variant="outlined">
      <Flex vertical gap="middle">
        {tasks.map((task) => (
          <Flex key={task.id} justify="space-between" align="center" gap="large" wrap>
            <Space orientation="vertical" size={2} style={{ minWidth: 220 }}>
              <Space wrap>
                <Typography.Text strong>{taskTypeLabels[task.task_type]}</Typography.Text>
                <TaskStatusTag status={task.status} />
              </Space>
              <Typography.Text type="secondary">
                {task.status === 'waiting_login' && <LoginOutlined />} {' '}
                {taskPhaseLabels[task.current_phase] || task.current_phase || '等待开始'}
              </Typography.Text>
            </Space>
            <div style={{ flex: '1 1 240px', maxWidth: 480 }}>
              <TaskProgress task={task} compact />
            </div>
            <Button type="link" icon={<RightOutlined />} onClick={() => onView(task.id)}>
              查看任务
            </Button>
          </Flex>
        ))}
      </Flex>
    </ProCard>
  );
}
