import { Alert, Button, Empty, Skeleton } from 'antd';
import type { ReactNode } from 'react';

export function QueryLoading({ rows = 5 }: { rows?: number }) {
  return <Skeleton active paragraph={{ rows }} />;
}

export function QueryError({ error, retry }: { error: unknown; retry?: () => void }) {
  const message = error instanceof Error ? error.message : '请求失败，请稍后重试';
  return (
    <Alert
      type="error"
      showIcon
      title="数据加载失败"
      description={message}
      action={retry ? <Button onClick={retry}>重试</Button> : undefined}
    />
  );
}

export function EmptyState({ description, action }: { description: ReactNode; action?: ReactNode }) {
  return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={description}>{action}</Empty>;
}
