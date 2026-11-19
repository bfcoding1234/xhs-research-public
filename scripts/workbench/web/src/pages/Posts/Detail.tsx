import { ExportOutlined, LinkOutlined } from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { history, Link, useLocation, useParams } from '@umijs/max';
import { Breadcrumb, Button, Result } from 'antd';
import { useState } from 'react';
import { QueryError, QueryLoading } from '@/components/QueryState';
import PostDetailContent from '@/features/posts/PostDetailContent';
import '@/features/posts/PostDetailDrawer.css';
import AddToProjectModal from '@/features/references/AddToProjectModal';
import { apiService } from '@/services/api';
import { queryKeys } from '@/services/queryKeys';
import { parsePostDetailNavigation, postDetailReturnPath } from '@/utils/postNavigation';

export default function PostDetailPage() {
  const params = useParams<{ id: string }>();
  const { search } = useLocation();
  const id = Number(params.id);
  const navigation = parsePostDetailNavigation(search);
  const [linking, setLinking] = useState(false);
  const post = useQuery({
    queryKey: queryKeys.post(id),
    queryFn: ({ signal }) => apiService.post(id, signal),
    enabled: Number.isInteger(id) && id > 0,
  });

  if (!Number.isInteger(id) || id <= 0) {
    return (
      <Result
        status="404"
        title="帖子不存在"
        extra={<Button onClick={() => history.push(postDetailReturnPath(navigation))}>返回上一层</Button>}
      />
    );
  }
  if (post.isPending) return <PageContainer><QueryLoading rows={8} /></PageContainer>;
  if (post.isError) {
    return <PageContainer><QueryError error={post.error} retry={() => post.refetch()} /></PageContainer>;
  }

  const value = post.data;
  const projectIds = value.projects?.map((project) => project.id) ?? [];
  const returnPath = postDetailReturnPath(navigation);
  const project =
    navigation.source === 'project'
      ? value.projects?.find((item) => item.id === navigation.projectId)
      : undefined;
  const parentLabel =
    navigation.source === 'project'
      ? `${project?.name ?? `项目 #${navigation.projectId}`} · 帖子`
      : navigation.source === 'author'
        ? `${navigation.base === 'my-projects' ? '个人' : value.author_name || `作者 #${navigation.authorId}`} · 帖子`
        : '帖子';
  const breadcrumbItems = [
    { title: <Link to={returnPath}>{parentLabel}</Link> },
    { title: '帖子详情' },
  ];

  return (
    <PageContainer
      title="帖子详情"
      breadcrumbRender={() => <Breadcrumb items={breadcrumbItems} />}
      onBack={() => history.push(returnPath)}
      extra={[
        <Button key="link" type="primary" icon={<LinkOutlined />} onClick={() => setLinking(true)}>
          关联到项目
        </Button>,
        value.note_url ? (
          <Button key="source" icon={<ExportOutlined />} href={value.note_url} target="_blank">
            打开原帖
          </Button>
        ) : null,
      ]}
    >
      <PostDetailContent mode="page" post={value} />
      <AddToProjectModal
        open={linking}
        entityType="post"
        entityIds={[id]}
        existingProjectIds={projectIds}
        onClose={() => setLinking(false)}
      />
    </PageContainer>
  );
}
