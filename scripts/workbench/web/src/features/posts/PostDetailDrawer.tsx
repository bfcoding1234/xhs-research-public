import { ExportOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { Alert, Button, Drawer } from 'antd';
import { apiService } from '@/services/api';
import { queryKeys } from '@/services/queryKeys';
import type { Post } from '@/types';
import './PostDetailDrawer.css';
import PostDetailContent from './PostDetailContent';

export default function PostDetailDrawer({
  summary,
  onClose,
}: {
  summary?: Post;
  onClose: () => void;
}) {
  const postId = summary?.id;
  const post = useQuery({
    queryKey: queryKeys.post(postId || 0),
    queryFn: ({ signal }) => apiService.post(postId || 0, signal),
    enabled: Boolean(postId),
  });
  const value = post.data;

  return (
    <Drawer
      rootClassName="post-detail-drawer-root"
      className="post-detail-drawer"
      title="帖子详情"
      open={Boolean(postId)}
      onClose={onClose}
      size={960}
      loading={post.isPending}
      destroyOnHidden
      extra={
        value?.note_url ? (
          <Button icon={<ExportOutlined />} href={value.note_url} target="_blank">
            打开原帖
          </Button>
        ) : null
      }
    >
      {post.isError ? (
        <Alert
          type="error"
          showIcon
          title="帖子详情加载失败"
          description={post.error.message}
          action={<Button onClick={() => post.refetch()}>重试</Button>}
        />
      ) : null}
      {value ? <PostDetailContent mode="drawer" post={value} /> : null}
    </Drawer>
  );
}
