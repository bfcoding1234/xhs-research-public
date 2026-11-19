import { Progress, Space, Typography } from 'antd';
import type { Task } from '@/types';
import { taskPercent } from '@/utils/format';

export default function TaskProgress({ task, compact = false }: { task: Task; compact?: boolean }) {
  const percent = taskPercent(task);
  const status =
    task.status === 'failed' ? 'exception' : task.status === 'completed' ? 'success' : 'normal';
  if (compact) {
    return (
      <Progress
        aria-label={`任务进度 ${percent}%`}
        percent={percent}
        showInfo={false}
        size="small"
        status={status}
      />
    );
  }
  return (
    <Space orientation="vertical" size={4} style={{ width: '100%' }}>
      <Progress percent={percent} status={status} />
      <Typography.Text type="secondary">
        {task.progress_total
          ? `${task.progress_current.toLocaleString('zh-CN')} / ${task.progress_total.toLocaleString('zh-CN')}`
          : '等待进度数据'}
      </Typography.Text>
    </Space>
  );
}
