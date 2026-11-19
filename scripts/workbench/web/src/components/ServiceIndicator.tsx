import { useQuery } from '@tanstack/react-query';
import { Badge, Tooltip, Typography } from 'antd';
import { apiService } from '@/services/api';
import { queryKeys } from '@/services/queryKeys';

export default function ServiceIndicator() {
  const health = useQuery({
    queryKey: queryKeys.health,
    queryFn: ({ signal }) => apiService.health(signal),
    refetchInterval: 15_000,
    retry: 1,
  });
  const status = health.isPending ? 'processing' : health.isError ? 'error' : 'success';
  const text = health.isPending ? '正在连接' : health.isError ? '服务不可用' : '本地服务';
  return (
    <Tooltip title={health.data ? `版本 ${health.data.version} · 数据仅保存在本机` : undefined}>
      <span className="service-indicator">
        <Badge status={status} />
        <Typography.Text type="secondary">{text}</Typography.Text>
      </span>
    </Tooltip>
  );
}
