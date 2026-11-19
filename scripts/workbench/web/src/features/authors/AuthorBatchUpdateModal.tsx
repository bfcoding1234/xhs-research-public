import { FileSearchOutlined, IdcardOutlined, InfoCircleOutlined } from '@ant-design/icons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, App, Checkbox, Form, InputNumber, Modal, Space, Typography } from 'antd';
import { useEffect, useState } from 'react';
import { apiService } from '@/services/api';
import { queryKeys } from '@/services/queryKeys';
import {
  buildAuthorBasicInfoUpdateConfiguration,
  buildAuthorPostUpdateConfiguration,
} from './AuthorUpdateModal';
import type { AuthorUpdateValues } from './AuthorUpdateModal';
import {
  submitAuthorUpdateBatch,
  type AuthorBatchResult,
  type BatchAuthor,
} from './authorBatchUpdate';

export type AuthorBatchUpdateMode = 'basic_info' | 'posts';

interface AuthorBatchUpdateModalProps {
  open: boolean;
  mode: AuthorBatchUpdateMode;
  authors: BatchAuthor[];
  onClose: () => void;
  onComplete: (result: AuthorBatchResult) => void;
  onSubmittingChange?: (submitting: boolean) => void;
}

function selectedAuthorsDescription(authors: BatchAuthor[]) {
  const names = authors.slice(0, 5).map((author) => author.display_name || author.author_id);
  const remaining = authors.length - names.length;
  return `${names.join('、')}${remaining > 0 ? ` 等 ${authors.length} 位作者` : ''}`;
}

export default function AuthorBatchUpdateModal({
  open,
  mode,
  authors,
  onClose,
  onComplete,
  onSubmittingChange,
}: AuthorBatchUpdateModalProps) {
  const [form] = Form.useForm<AuthorUpdateValues>();
  const [submitting, setSubmitting] = useState(false);
  const [progress, setProgress] = useState({ completed: 0, total: 0 });
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: queryKeys.settings,
    queryFn: ({ signal }) => apiService.settings(signal),
    enabled: open && mode === 'posts',
  });
  const scopes = Form.useWatch('scopes', form) ?? [];
  const maxPostLimit = settings.data?.max_author_notes ?? 300;

  useEffect(() => {
    if (!open || mode !== 'posts' || !settings.data) return;
    form.setFieldsValue({
      scopes: ['preview_posts'],
      previewLimit: Math.min(settings.data.default_discovery, maxPostLimit),
      detailLimit: Math.min(Math.max(settings.data.default_deep, 1), maxPostLimit),
    });
  }, [form, maxPostLimit, mode, open, settings.data]);

  const setBatchSubmitting = (value: boolean) => {
    setSubmitting(value);
    onSubmittingChange?.(value);
  };

  const submit = async () => {
    try {
      const values = mode === 'posts' ? await form.validateFields() : undefined;
      setBatchSubmitting(true);
      setProgress({ completed: 0, total: authors.length });
      const result = await submitAuthorUpdateBatch(
        authors,
        (author) =>
          apiService.createTask(
            undefined,
            'author',
            mode === 'basic_info'
              ? buildAuthorBasicInfoUpdateConfiguration(author)
              : buildAuthorPostUpdateConfiguration(author, values as AuthorUpdateValues),
          ),
        (completed, total) => setProgress({ completed, total }),
      );
      await queryClient.invalidateQueries({ queryKey: queryKeys.tasks });
      onComplete(result);
      onClose();
    } catch (error) {
      if (error && typeof error === 'object' && 'errorFields' in error) return;
      message.error(error instanceof Error ? error.message : '批量更新任务创建失败');
    } finally {
      setBatchSubmitting(false);
      setProgress({ completed: 0, total: 0 });
    }
  };

  const isPostSettingsUnavailable = mode === 'posts' && !settings.data;
  const title = mode === 'basic_info' ? '批量更新作者信息' : '批量更新帖子信息';
  const okText = submitting
    ? `正在创建 ${progress.completed}/${progress.total}`
    : `创建 ${authors.length} 个更新任务`;

  return (
    <Modal
      title={title}
      open={open}
      loading={mode === 'posts' && settings.isPending}
      okText={okText}
      cancelText="取消"
      confirmLoading={submitting}
      okButtonProps={{ disabled: isPostSettingsUnavailable || authors.length === 0 }}
      cancelButtonProps={{ disabled: submitting }}
      closable={!submitting}
      keyboard={!submitting}
      mask={{ closable: !submitting }}
      onOk={() => void submit()}
      onCancel={() => {
        if (!submitting) onClose();
      }}
      destroyOnHidden
      width={620}
    >
      <Alert
        type="info"
        showIcon
        icon={<InfoCircleOutlined />}
        title={`已选择 ${authors.length} 位作者`}
        description={
          <Space orientation="vertical" size={2}>
            <span>{selectedAuthorsDescription(authors)}</span>
            <span>系统将为每位作者创建一个独立任务；创建成功不代表数据已经更新完成。</span>
          </Space>
        }
        style={{ marginBottom: 20 }}
      />

      {mode === 'basic_info' ? (
        <Typography.Paragraph>
          本次只刷新作者名称、头像、简介、粉丝等基础资料，不读取作者帖子。
        </Typography.Paragraph>
      ) : (
        <>
          {settings.isError ? (
            <Alert
              type="error"
              showIcon
              title="更新参数加载失败"
              description={settings.error.message}
              style={{ marginBottom: 20 }}
            />
          ) : null}
          <Form form={form} layout="vertical" disabled={submitting || !settings.data}>
            <Form.Item
              name="scopes"
              label="更新内容"
              rules={[{ required: true, type: 'array', min: 1, message: '请至少选择一项更新内容' }]}
            >
              <Checkbox.Group style={{ display: 'grid', gap: 12 }}>
                <Checkbox value="preview_posts">
                  <Space align="start">
                    <IdcardOutlined />
                    <span>
                      <Typography.Text strong>帖子基础信息（批量预览）</Typography.Text>
                      <br />
                      <Typography.Text type="secondary">
                        按每位作者更新标题、点赞、链接、发布时间和封面
                      </Typography.Text>
                    </span>
                  </Space>
                </Checkbox>
                <Checkbox value="detailed_posts">
                  <Space align="start">
                    <FileSearchOutlined />
                    <span>
                      <Typography.Text strong>帖子详细信息（逐篇打开）</Typography.Text>
                      <br />
                      <Typography.Text type="secondary">
                        按每位作者逐篇补充正文、收藏、评论和完整媒体，耗时更长
                      </Typography.Text>
                    </span>
                  </Space>
                </Checkbox>
              </Checkbox.Group>
            </Form.Item>
            {scopes.includes('preview_posts') ? (
              <Form.Item
                name="previewLimit"
                label="每位作者最多批量更新帖子数"
                extra={`每位作者最多处理 ${maxPostLimit} 篇`}
                rules={[{ required: true, message: '请填写批量更新数量' }]}
              >
                <InputNumber min={1} max={maxPostLimit} precision={0} style={{ width: '100%' }} />
              </Form.Item>
            ) : null}
            {scopes.includes('detailed_posts') ? (
              <Form.Item
                name="detailLimit"
                label="每位作者最多逐篇更新帖子数"
                extra={`详细信息需要逐篇打开；每位作者最多 ${maxPostLimit} 篇`}
                rules={[{ required: true, message: '请填写逐篇更新数量' }]}
              >
                <InputNumber min={1} max={maxPostLimit} precision={0} style={{ width: '100%' }} />
              </Form.Item>
            ) : null}
          </Form>
        </>
      )}
    </Modal>
  );
}
