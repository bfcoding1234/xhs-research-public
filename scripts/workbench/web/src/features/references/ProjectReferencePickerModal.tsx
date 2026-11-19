import { LinkOutlined } from '@ant-design/icons';
import type { ProColumns } from '@ant-design/pro-components';
import { ProTable } from '@ant-design/pro-components';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, App, Button, Input, Modal, Space, Typography } from 'antd';
import { useDeferredValue, useEffect, useMemo, useState } from 'react';
import { apiService } from '@/services/api';
import { queryKeys } from '@/services/queryKeys';
import type { Author, Post, PostQuery } from '@/types';
import { formatNumber } from '@/utils/format';
import { createPersistentRowSelection } from '@/features/selection/persistentRowSelection';
import {
  filterProjectReferenceCandidates,
  type ReferenceEntity,
  type ReferenceEntityType,
} from './projectReferenceCandidates';

interface ProjectReferencePickerModalProps {
  open: boolean;
  projectId: number;
  entityType: ReferenceEntityType;
  onClose: () => void;
}

export default function ProjectReferencePickerModal({
  open,
  projectId,
  entityType,
  onClose,
}: ProjectReferencePickerModalProps) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [query, setQuery] = useState('');
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const deferredQuery = useDeferredValue(query);
  const entityLabel = entityType === 'post' ? '帖子' : '作者';
  const postQuery = useMemo<PostQuery>(() => ({
    page,
    page_size: pageSize,
    query: deferredQuery,
    type: 'all',
    detail: 'all',
    ocr: 'all',
    vision: 'all',
    sort: 'default',
    exclude_project_id: projectId,
  }), [deferredQuery, page, pageSize, projectId]);
  const postReferences = useQuery({
    queryKey: [...queryKeys.posts, 'project-reference-picker', postQuery],
    queryFn: ({ signal }) => apiService.posts(postQuery, signal),
    enabled: open && entityType === 'post',
    placeholderData: (previous) => previous,
  });
  const authorReferences = useQuery({
    queryKey: queryKeys.authors,
    queryFn: ({ signal }) => apiService.authors(signal),
    enabled: open && entityType === 'author',
  });
  const referenceIds = useQuery({
    queryKey: queryKeys.projectReferenceIds(projectId),
    queryFn: ({ signal }) => apiService.projectReferenceIds(projectId, signal),
    enabled: open && entityType === 'author',
  });
  const existingEntityIds = referenceIds.data?.author_ids ?? [];

  useEffect(() => {
    if (!open) {
      setQuery('');
      setSelectedIds([]);
      setPage(1);
      setPageSize(10);
    }
  }, [entityType, open]);

  const available = useMemo(
    () =>
      entityType === 'post'
        ? (postReferences.data?.items ?? [])
        : filterProjectReferenceCandidates(
            authorReferences.data ?? [],
            entityType,
            existingEntityIds,
            '',
          ),
    [authorReferences.data, entityType, existingEntityIds, postReferences.data?.items],
  );
  const data = useMemo(
    () => entityType === 'post'
      ? available
      : filterProjectReferenceCandidates(available, entityType, [], query),
    [available, entityType, query],
  );
  const total = entityType === 'post' ? (postReferences.data?.total ?? 0) : available.length;
  const referencesPending = entityType === 'post'
    ? postReferences.isPending
    : authorReferences.isPending || referenceIds.isPending;
  const referencesError = entityType === 'post'
    ? postReferences.error
    : authorReferences.error ?? referenceIds.error;
  const refetchReferences = () => entityType === 'post'
    ? postReferences.refetch()
    : Promise.all([authorReferences.refetch(), referenceIds.refetch()]);

  const mutation = useMutation({
    mutationFn: () =>
      apiService.addProjectReferences(projectId, {
        post_ids: entityType === 'post' ? selectedIds : [],
        author_ids: entityType === 'author' ? selectedIds : [],
      }),
    onSuccess: async (result) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.projects }),
        queryClient.invalidateQueries({ queryKey: queryKeys.posts }),
        queryClient.invalidateQueries({ queryKey: queryKeys.authors }),
        queryClient.invalidateQueries({ queryKey: queryKeys.project(projectId), exact: true }),
        queryClient.invalidateQueries({ queryKey: queryKeys.projectPosts(projectId), exact: false }),
        queryClient.invalidateQueries({ queryKey: queryKeys.projectPostCoverage(projectId), exact: true }),
        queryClient.invalidateQueries({ queryKey: queryKeys.projectReferenceIds(projectId) }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.projectAuthors(projectId),
          exact: true,
        }),
      ]);
      if (entityType === 'post') {
        const authorSummary = result.added_author_count
          ? `，并新增关联 ${result.added_author_count} 位帖子作者`
          : '';
        message.success(`已关联 ${result.added_post_count} 个帖子${authorSummary}`);
      } else {
        message.success(`已关联 ${result.added_author_count} 位作者`);
      }
      onClose();
    },
    onError: (error) => message.error(error.message),
  });

  const columns: ProColumns<ReferenceEntity>[] =
    entityType === 'post'
      ? [
          {
            title: '帖子',
            dataIndex: 'title',
            width: 300,
            fixed: 'left',
            render: (_, entity) => {
              const post = entity as Post;
              return (
                <Space orientation="vertical" size={0}>
                  <Typography.Text>{post.title || post.note_id}</Typography.Text>
                  <Typography.Text type="secondary">
                    {post.author_name || '未知作者'}
                  </Typography.Text>
                </Space>
              );
            },
          },
          {
            title: '帖子 ID',
            dataIndex: 'note_id',
            width: 220,
            ellipsis: true,
          },
          {
            title: '点赞',
            dataIndex: 'likes_count',
            width: 100,
            align: 'right',
            renderText: formatNumber,
          },
        ]
      : [
          {
            title: '作者',
            dataIndex: 'display_name',
            width: 280,
            fixed: 'left',
            render: (_, entity) => {
              const author = entity as Author;
              return (
                <Space orientation="vertical" size={0}>
                  <Typography.Text>{author.display_name || author.author_id}</Typography.Text>
                  <Typography.Text type="secondary" className="mono">
                    {author.author_id}
                  </Typography.Text>
                </Space>
              );
            },
          },
          {
            title: '小红书号',
            dataIndex: 'xhs_id',
            width: 180,
            renderText: (value: string) => value || '—',
          },
          {
            title: '粉丝',
            dataIndex: 'followers_count',
            width: 110,
            align: 'right',
            renderText: formatNumber,
          },
        ];

  return (
    <Modal
      title={
        <Space>
          <LinkOutlined />
          关联{entityLabel}
        </Space>
      }
      open={open}
      width={900}
      okText={`关联所选${entityLabel}${selectedIds.length ? `（${selectedIds.length}）` : ''}`}
      cancelText="取消"
      confirmLoading={mutation.isPending}
      okButtonProps={{ disabled: selectedIds.length === 0 || selectedIds.length > 500 }}
      onCancel={onClose}
      onOk={() => mutation.mutate()}
      destroyOnHidden
    >
      <Typography.Paragraph type="secondary">
        从全局{entityLabel}中选择尚未加入本项目的内容。这里只新增项目引用，不会复制或移动全局数据。
      </Typography.Paragraph>
      {referencesError ? (
        <Alert
          showIcon
          type="error"
          title={`${entityLabel}列表加载失败`}
          description={referencesError.message}
          action={
            <Button
              size="small"
              onClick={() => void refetchReferences()}
            >
              重试
            </Button>
          }
          style={{ marginBottom: 16 }}
        />
      ) : null}
      <ProTable<ReferenceEntity>
        rowKey="id"
        headerTitle={`可关联${entityLabel}（${total}）`}
        loading={referencesPending}
        columns={columns}
        dataSource={data}
        search={false}
        scroll={{ x: 760, y: 420 }}
        pagination={entityType === 'post'
          ? {
              current: postReferences.data?.page ?? page,
              pageSize: postReferences.data?.page_size ?? pageSize,
              total,
              showSizeChanger: true,
              onChange: (nextPage, nextPageSize) => {
                setPage(nextPage);
                setPageSize(nextPageSize);
              },
            }
          : { defaultPageSize: 10, showSizeChanger: true }}
        options={{ reload: false, density: true, setting: false, fullScreen: false }}
        locale={{
          emptyText:
            referencesPending
              ? '正在加载…'
              : `没有可关联的${entityLabel}`,
        }}
        rowSelection={createPersistentRowSelection<ReferenceEntity>(
          selectedIds,
          setSelectedIds,
        )}
        toolbar={{
          filter: (
            <Input.Search
              allowClear
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setPage(1);
              }}
              placeholder={
                entityType === 'post'
                  ? '搜索标题、作者或帖子 ID'
                  : '搜索作者名、作者 ID、小红书号或简介'
              }
              style={{ width: 340 }}
            />
          ),
        }}
      />
      {selectedIds.length > 500 ? (
        <Alert type="warning" showIcon title="单次最多关联 500 条，请减少选择数量" />
      ) : null}
    </Modal>
  );
}
