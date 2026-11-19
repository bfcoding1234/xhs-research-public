import { Tag } from 'antd';
import type { TaskStatus } from '@/types';
import { taskStatusLabels } from '@/utils/format';

const colors: Record<TaskStatus, string> = {
  queued: 'gold',
  running: 'processing',
  waiting_login: 'error',
  completed: 'success',
  partial: 'warning',
  failed: 'error',
  cancelled: 'default',
};

export default function TaskStatusTag({ status }: { status?: TaskStatus }) {
  if (!status) return <Tag>未运行</Tag>;
  return <Tag color={colors[status]}>{taskStatusLabels[status]}</Tag>;
}
