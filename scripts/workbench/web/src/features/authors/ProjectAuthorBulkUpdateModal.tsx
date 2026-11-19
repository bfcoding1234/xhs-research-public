import { FileSearchOutlined, IdcardOutlined, InfoCircleOutlined } from '@ant-design/icons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Alert, App, Checkbox, Form, InputNumber, Modal, Radio, Space, Typography } from 'antd';
import { useEffect, useMemo } from 'react';
import { apiService } from '@/services/api';
import { queryKeys } from '@/services/queryKeys';
import type {
  AppSettings,
  Author,
  Project,
  ProjectAuthorUpdateConfiguration,
  TaskReceipt,
} from '@/types';

type Scope = ProjectAuthorUpdateConfiguration['scopes'][number];
type Target = ProjectAuthorUpdateConfiguration['target'];

type Values = Omit<ProjectAuthorUpdateConfiguration, 'scopes'> & {
  scopes: Scope[];
};

function numeric(value: unknown): number {
  return Math.max(0, Number(value) || 0);
}

function countTargets(authors: Author[], target: Target): number {
  if (target === 'basic_unupdated') {
    return authors.filter((author) => !author.last_profile_fetched_at).length;
  }
  if (target === 'posts_unupdated') {
    return authors.filter(
      (author) =>
        numeric(author.project_post_count) === 0 &&
        numeric(author.stored_post_count ?? author.post_count) === 0,
    ).length;
  }
  return authors.length;
}

export default function ProjectAuthorBulkUpdateModal({
  project,
  authors,
  settings,
  open,
  onClose,
  onCreated,
}: {
  project: Project;
  authors: Author[];
  settings: AppSettings;
  open: boolean;
  onClose: () => void;
  onCreated: (task: TaskReceipt) => void | Promise<void>;
}) {
  const [form] = Form.useForm<Values>();
  const target = Form.useWatch('target', form) ?? 'basic_unupdated';
  const scopes = Form.useWatch('scopes', form) ?? [];
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const targetCount = useMemo(() => countTargets(authors, target), [authors, target]);
  const maxAuthorNotes = settings.max_author_notes ?? 300;
  const mutation = useMutation({
    mutationFn: (values: Values) => apiService.startProjectAuthorUpdates(project.id, values),
    onSuccess: async (task) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.projectTasks(project.id), exact: true }),
        queryClient.invalidateQueries({ queryKey: queryKeys.tasks, exact: true }),
      ]);
      onClose();
      await onCreated(task);
    },
    onError: (error) =>
      message.error(error instanceof Error ? error.message : '批量作者更新任务创建失败'),
  });

  useEffect(() => {
    if (!open) return;
    form.setFieldsValue({
      scopes: ['basic_info', 'preview_posts'],
      target: 'basic_unupdated',
      batch_size: 10,
      max_authors: 100,
      preview_limit: Math.min(settings.default_discovery ?? 20, maxAuthorNotes),
      detail_limit: Math.min(Math.max(settings.default_deep ?? 5, 1), maxAuthorNotes),
      author_delay_min_seconds: 1,
      author_delay_max_seconds: 3,
      batch_delay_min_seconds: 2,
      batch_delay_max_seconds: 5,
      consecutive_failure_limit: 5,
    });
  }, [
    form,
    maxAuthorNotes,
    open,
    settings.default_deep,
    settings.default_discovery,
  ]);

  const submit = async () => {
    const values = await form.validateFields();
    mutation.mutate(values);
  };

  return (
    <Modal
      title="更新未更新作者"
      open={open}
      okText="创建更新任务"
      cancelText="取消"
      confirmLoading={mutation.isPending}
      onOk={() => void submit()}
      onCancel={onClose}
      destroyOnHidden
      width={720}
    >
      <Alert
        type="info"
        showIcon
        icon={<InfoCircleOutlined />}
        title={`将在项目「${project.name}」内创建一个批量作者更新任务`}
        description="系统会在一个任务里按批次低频执行，遇到登录或安全验证时会暂停；处理完成后可在任务详情继续。"
        style={{ marginBottom: 20 }}
      />
      <Form form={form} layout="vertical">
        <Form.Item
          name="scopes"
          label="更新范围"
          rules={[{ required: true, type: 'array', min: 1, message: '请至少选择一项更新范围' }]}
        >
          <Checkbox.Group style={{ display: 'grid', gap: 12 }}>
            <Checkbox value="basic_info">
              <Space align="start">
                <IdcardOutlined />
                <span>
                  <Typography.Text strong>基础信息</Typography.Text>
                  <br />
                  <Typography.Text type="secondary">
                    更新昵称、头像、简介、粉丝等作者主页资料
                  </Typography.Text>
                </span>
              </Space>
            </Checkbox>
            <Checkbox value="preview_posts">
              <Space align="start">
                <IdcardOutlined />
                <span>
                  <Typography.Text strong>帖子基础信息</Typography.Text>
                  <br />
                  <Typography.Text type="secondary">
                    通过作者主页预览模式更新标题、点赞、链接、发布时间和封面
                  </Typography.Text>
                </span>
              </Space>
            </Checkbox>
            <Checkbox value="detailed_posts">
              <Space align="start">
                <FileSearchOutlined />
                <span>
                  <Typography.Text strong>帖子详细信息</Typography.Text>
                  <br />
                  <Typography.Text type="secondary">
                    逐篇打开帖子，补充正文、收藏、评论和完整媒体；访问更频繁，默认不勾选
                  </Typography.Text>
                </span>
              </Space>
            </Checkbox>
          </Checkbox.Group>
        </Form.Item>
        <Form.Item name="target" label="目标作者" rules={[{ required: true }]}>
          <Radio.Group>
            <Space orientation="vertical">
              <Radio value="basic_unupdated">
                基础信息未更新的作者（当前约 {countTargets(authors, 'basic_unupdated')} 位）
              </Radio>
              <Radio value="posts_unupdated">
                帖子信息未更新的作者（当前约 {countTargets(authors, 'posts_unupdated')} 位）
              </Radio>
              <Radio value="all">当前项目全部作者（当前 {authors.length} 位）</Radio>
            </Space>
          </Radio.Group>
        </Form.Item>
        <Alert
          type={targetCount ? 'success' : 'warning'}
          showIcon
          title={
            targetCount
              ? `当前筛选约 ${targetCount} 位作者；实际任务最多处理下方设置的数量。`
              : '当前筛选条件下没有可更新作者'
          }
          style={{ marginBottom: 20 }}
        />
        <Space align="start" size="middle" wrap>
          <Form.Item
            name="batch_size"
            label="批次大小"
            rules={[{ required: true, message: '请填写批次大小' }]}
          >
            <InputNumber min={1} max={50} precision={0} />
          </Form.Item>
          <Form.Item
            name="max_authors"
            label="最大处理作者数"
            rules={[{ required: true, message: '请填写最大处理作者数' }]}
          >
            <InputNumber min={1} max={500} precision={0} />
          </Form.Item>
          <Form.Item
            name="consecutive_failure_limit"
            label="连续失败阈值"
            rules={[{ required: true, message: '请填写连续失败阈值' }]}
          >
            <InputNumber min={1} max={20} precision={0} />
          </Form.Item>
        </Space>
        {scopes.includes('preview_posts') ? (
          <Form.Item
            name="preview_limit"
            label="每位作者最多更新帖子基础信息数"
            extra={`最多 ${maxAuthorNotes} 篇`}
            rules={[{ required: true, message: '请填写帖子基础信息数量' }]}
          >
            <InputNumber min={1} max={maxAuthorNotes} precision={0} style={{ width: 240 }} />
          </Form.Item>
        ) : null}
        {scopes.includes('detailed_posts') ? (
          <Form.Item
            name="detail_limit"
            label="每位作者最多更新帖子详细信息数"
            extra={`逐篇打开帖子，建议保持较小数量；最多 ${maxAuthorNotes} 篇`}
            rules={[{ required: true, message: '请填写帖子详细信息数量' }]}
          >
            <InputNumber min={1} max={maxAuthorNotes} precision={0} style={{ width: 240 }} />
          </Form.Item>
        ) : null}
        <Typography.Title level={5}>安全间隔</Typography.Title>
        <Space align="start" size="middle" wrap>
          <Form.Item name="author_delay_min_seconds" label="作者间隔最短秒数">
            <InputNumber min={0} precision={0} />
          </Form.Item>
          <Form.Item name="author_delay_max_seconds" label="作者间隔最长秒数">
            <InputNumber min={0} precision={0} />
          </Form.Item>
          <Form.Item name="batch_delay_min_seconds" label="批次间隔最短秒数">
            <InputNumber min={0} precision={0} />
          </Form.Item>
          <Form.Item name="batch_delay_max_seconds" label="批次间隔最长秒数">
            <InputNumber min={0} precision={0} />
          </Form.Item>
        </Space>
      </Form>
    </Modal>
  );
}
