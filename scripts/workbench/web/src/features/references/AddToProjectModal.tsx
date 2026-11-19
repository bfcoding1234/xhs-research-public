import { LinkOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, App, Modal, Select, Space, Typography } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { apiService } from '@/services/api';
import { queryKeys } from '@/services/queryKeys';

interface AddToProjectModalProps {
  open: boolean;
  entityType: 'post' | 'author';
  entityIds: number[];
  existingProjectIds?: number[];
  onClose: () => void;
  onSuccess?: (projectId: number) => void;
}

export default function AddToProjectModal({
  open,
  entityType,
  entityIds,
  existingProjectIds = [],
  onClose,
  onSuccess,
}: AddToProjectModalProps) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [projectId, setProjectId] = useState<number>();
  const projects = useQuery({
    queryKey: queryKeys.projects,
    queryFn: ({ signal }) => apiService.projects(signal),
    enabled: open,
  });

  useEffect(() => {
    if (!open) setProjectId(undefined);
  }, [open]);

  const existing = useMemo(() => new Set(existingProjectIds), [existingProjectIds]);
  const mutation = useMutation({
    mutationFn: (targetProjectId: number) =>
      apiService.addProjectReferences(targetProjectId, {
        post_ids: entityType === 'post' ? entityIds : [],
        author_ids: entityType === 'author' ? entityIds : [],
      }),
    onSuccess: async (result) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.projects }),
        queryClient.invalidateQueries({ queryKey: queryKeys.posts }),
        queryClient.invalidateQueries({ queryKey: queryKeys.authors }),
        queryClient.invalidateQueries({ queryKey: queryKeys.project(result.project_id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.projectPosts(result.project_id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.projectAuthors(result.project_id) }),
        ...entityIds.map((id) =>
          queryClient.invalidateQueries({
            queryKey: entityType === 'post' ? queryKeys.post(id) : queryKeys.author(id),
          }),
        ),
      ]);
      const added =
        entityType === 'post' ? result.added_post_count : result.added_author_count;
      if (added > 0) {
        message.success(`已将 ${added} 个${entityType === 'post' ? '帖子' : '作者'}关联到项目`);
      } else {
        message.info('所选内容已经关联到该项目');
      }
      onSuccess?.(result.project_id);
      onClose();
    },
    onError: (error) => message.error(error.message),
  });

  return (
    <Modal
      title={
        <Space>
          <LinkOutlined />
          关联到项目
        </Space>
      }
      open={open}
      okText="确认关联"
      cancelText="取消"
      confirmLoading={mutation.isPending}
      okButtonProps={{ disabled: !projectId || entityIds.length === 0 }}
      onCancel={onClose}
      onOk={() => projectId && mutation.mutate(projectId)}
      destroyOnHidden
    >
      <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
        <Typography.Text type="secondary">
          将选中的 {entityIds.length} 个{entityType === 'post' ? '帖子' : '作者'}作为引用加入项目，
          全局原始数据不会被复制或移动。
        </Typography.Text>
        {projects.isError ? (
          <Alert
            showIcon
            type="error"
            title="项目列表加载失败"
            description={projects.error.message}
          />
        ) : null}
        <Select
          aria-label="选择要关联的项目"
          value={projectId}
          onChange={setProjectId}
          loading={projects.isPending}
          placeholder="选择项目"
          showSearch={{ optionFilterProp: 'label' }}
          style={{ width: '100%' }}
          options={(projects.data ?? []).map((project) => ({
            value: project.id,
            label: `${project.name}（${project.post_count ?? 0} 篇 / ${project.author_count ?? 0} 位）`,
            disabled: existing.has(project.id),
          }))}
          notFoundContent={projects.isPending ? '正在加载…' : '暂无项目，请先创建项目'}
        />
      </Space>
    </Modal>
  );
}
