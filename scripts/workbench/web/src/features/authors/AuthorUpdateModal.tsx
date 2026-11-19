import { FileSearchOutlined, IdcardOutlined } from '@ant-design/icons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, App, Checkbox, Form, InputNumber, Modal, Space, Typography } from 'antd';
import { useEffect, useState } from 'react';
import { apiService } from '@/services/api';
import { queryKeys } from '@/services/queryKeys';
import type { Author, ResearchConfiguration, TaskReceipt } from '@/types';

export type AuthorUpdateScope = 'preview_posts' | 'detailed_posts';

export interface AuthorUpdateValues {
  scopes: AuthorUpdateScope[];
  previewLimit: number;
  detailLimit: number;
}

interface AuthorUpdateModalProps {
  open: boolean;
  author: Author;
  onClose: () => void;
  onCreated: (task: TaskReceipt) => void | Promise<void>;
}

function baseAuthorUpdateConfiguration(
  author: Pick<Author, 'author_id' | 'display_name'>,
): ResearchConfiguration {
  return {
    topic: `更新作者基础信息：${author.display_name || author.author_id}`,
    source: {
      profile_urls: [],
      author_ids: [author.author_id],
      keywords: [],
      filters: {},
    },
    limits: { discovery: 1, deep: 0 },
    keyword_limits: { discovery: 1, deep: 0 },
    author_limits: { discovery: 1, deep: 0 },
    image_analysis: { mode: 'ocr-only', vision_ratio: 0, vision_count: 0 },
    force_refresh: true,
    author_update: { scopes: ['basic_info'] },
  };
}

export function buildAuthorBasicInfoUpdateConfiguration(
  author: Pick<Author, 'author_id' | 'display_name'>,
): ResearchConfiguration {
  return baseAuthorUpdateConfiguration(author);
}

export function buildAuthorPostUpdateConfiguration(
  author: Pick<Author, 'author_id' | 'display_name'>,
  values: AuthorUpdateValues,
): ResearchConfiguration {
  const previewPosts = values.scopes.includes('preview_posts');
  const detailedPosts = values.scopes.includes('detailed_posts');
  const previewLimit = previewPosts ? values.previewLimit : 1;
  const detailLimit = detailedPosts ? values.detailLimit : 0;
  const discoveryLimit = Math.max(previewLimit, detailLimit, 1);
  return {
    ...baseAuthorUpdateConfiguration(author),
    topic: `更新作者帖子：${author.display_name || author.author_id}`,
    limits: { discovery: discoveryLimit, deep: detailLimit },
    author_limits: { discovery: discoveryLimit, deep: detailLimit },
    author_update: { scopes: values.scopes },
  };
}

export default function AuthorUpdateModal({
  open,
  author,
  onClose,
  onCreated,
}: AuthorUpdateModalProps) {
  const [form] = Form.useForm<AuthorUpdateValues>();
  const [submitting, setSubmitting] = useState(false);
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: queryKeys.settings,
    queryFn: ({ signal }) => apiService.settings(signal),
    enabled: open,
  });
  const scopes = Form.useWatch('scopes', form) ?? [];
  const maxPostLimit = settings.data?.max_author_notes ?? 300;

  useEffect(() => {
    if (!open) return;
    form.setFieldsValue({
      scopes: ['preview_posts'],
      previewLimit: Math.min(settings.data?.default_discovery ?? 20, maxPostLimit),
      detailLimit: Math.min(Math.max(settings.data?.default_deep ?? 5, 1), maxPostLimit),
    });
  }, [form, maxPostLimit, open, settings.data?.default_deep, settings.data?.default_discovery]);

  const submit = async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      const task = await apiService.createTask(
        undefined,
        'author',
        buildAuthorPostUpdateConfiguration(author, values),
      );
      await queryClient.invalidateQueries({ queryKey: queryKeys.tasks });
      onClose();
      await onCreated(task);
    } catch (error) {
      if (error && typeof error === 'object' && 'errorFields' in error) return;
      message.error(error instanceof Error ? error.message : '帖子更新任务发起失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title={`更新「${author.display_name || author.author_id}」的帖子`}
      open={open}
      okText="发起更新任务"
      cancelText="取消"
      confirmLoading={submitting}
      onOk={submit}
      onCancel={onClose}
      destroyOnHidden
      width={600}
    >
      <Alert
        type="info"
        showIcon
        title="帖子信息分为批量预览和逐篇详情"
        description="默认只批量更新预览模式可见的基础信息；只有需要正文、收藏、评论或完整媒体时，再选择逐篇详情。"
        style={{ marginBottom: 20 }}
      />
      <Form form={form} layout="vertical">
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
                    通过作者主页预览模式批量更新标题、点赞、链接、发布时间和封面
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
                    逐篇打开帖子，补充正文、收藏、评论和完整媒体信息，耗时更长
                  </Typography.Text>
                </span>
              </Space>
            </Checkbox>
          </Checkbox.Group>
        </Form.Item>
        {scopes.includes('preview_posts') ? (
          <Form.Item
            name="previewLimit"
            label="最多批量更新帖子数"
            extra={`预览模式单次最多处理 ${maxPostLimit} 篇`}
            rules={[{ required: true, message: '请填写批量更新数量' }]}
          >
            <InputNumber min={1} max={maxPostLimit} precision={0} style={{ width: '100%' }} />
          </Form.Item>
        ) : null}
        {scopes.includes('detailed_posts') ? (
          <Form.Item
            name="detailLimit"
            label="最多逐篇更新帖子数"
            extra={`详细信息需要逐篇打开，建议先处理少量帖子；单次最多 ${maxPostLimit} 篇`}
            rules={[{ required: true, message: '请填写逐篇更新数量' }]}
          >
            <InputNumber min={1} max={maxPostLimit} precision={0} style={{ width: '100%' }} />
          </Form.Item>
        ) : null}
      </Form>
    </Modal>
  );
}
