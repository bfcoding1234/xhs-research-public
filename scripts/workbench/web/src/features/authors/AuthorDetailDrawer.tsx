import { ExportOutlined, FullscreenOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { history } from '@umijs/max';
import { Button, Drawer, Space } from 'antd';
import AuthorDetailPage from '@/pages/Authors/Detail';
import { apiService } from '@/services/api';
import { queryKeys } from '@/services/queryKeys';

export default function AuthorDetailDrawer({
  authorId,
  onClose,
}: {
  authorId?: number;
  onClose: () => void;
}) {
  const author = useQuery({
    queryKey: queryKeys.author(authorId || 0),
    queryFn: ({ signal }) => apiService.author(authorId || 0, signal),
    enabled: Boolean(authorId),
  });
  const value = author.data;
  return (
    <Drawer
      title={value?.display_name || value?.author_id || '作者详情'}
      open={Boolean(authorId)}
      onClose={onClose}
      size="min(1200px, calc(100vw - 24px))"
      loading={author.isPending}
      destroyOnHidden
      extra={
        authorId ? (
          <Space>
            <Button
              aria-label="查看完整详情"
              icon={<FullscreenOutlined />}
              onClick={() => history.push(`/authors/${authorId}`)}
            >
              查看完整详情
            </Button>
            {value?.profile_url ? (
              <Button icon={<ExportOutlined />} href={value.profile_url} target="_blank">
                打开主页
              </Button>
            ) : null}
          </Space>
        ) : null
      }
    >
      {authorId ? <AuthorDetailPage authorId={authorId} embedded showBack={false} /> : null}
    </Drawer>
  );
}
