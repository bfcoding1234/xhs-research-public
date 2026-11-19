import { DownOutlined, FileSearchOutlined, InfoCircleOutlined } from '@ant-design/icons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { MenuProps } from 'antd';
import {
  Alert,
  App,
  Button,
  Dropdown,
  Form,
  InputNumber,
  Modal,
  Radio,
  Space,
  Typography,
} from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { apiService } from '@/services/api';
import { queryKeys } from '@/services/queryKeys';
import type { AppSettings, PostDetailUpdateConfiguration, TaskReceipt } from '@/types';

type Scope = PostDetailUpdateConfiguration['scope'];
type Target = NonNullable<PostDetailUpdateConfiguration['target']>;
type Mode = PostDetailUpdateConfiguration['mode'];

interface PostSummary {
  id: number;
  detail_level?: string;
  last_detail_fetched_at?: string | null;
}

type BatchValues = Omit<
  PostDetailUpdateConfiguration,
  'mode' | 'scope' | 'scope_id' | 'post_ids'
>;
type DelaySettings = Pick<
  AppSettings,
  | 'post_delay_min_seconds'
  | 'post_delay_max_seconds'
  | 'batch_delay_min_seconds'
  | 'batch_delay_max_seconds'
>;

function isPreview(post: PostSummary) {
  return !post.detail_level || post.detail_level === 'card';
}

export default function PostDetailUpdateControl({
  posts,
  selectedIds,
  scope,
  scopeId,
  detailTtlDays = 30,
  delaySettings,
  onSelectionChange,
  onCreated,
}: {
  posts: PostSummary[];
  selectedIds: number[];
  scope: Scope;
  scopeId?: number;
  detailTtlDays?: number;
  delaySettings?: DelaySettings;
  onSelectionChange: (ids: number[]) => void;
  onCreated: (task: TaskReceipt) => void | Promise<void>;
}) {
  const [mode, setMode] = useState<Mode | null>(null);
  const [form] = Form.useForm<BatchValues>();
  const target = (Form.useWatch('target', form) ?? 'needs_update') as Target;
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const postDelayMin = delaySettings?.post_delay_min_seconds ?? 1;
  const postDelayMax = delaySettings?.post_delay_max_seconds ?? 3;
  const batchDelayMin = delaySettings?.batch_delay_min_seconds ?? 2;
  const batchDelayMax = delaySettings?.batch_delay_max_seconds ?? 5;
  const selected = useMemo(() => {
    const ids = new Set(selectedIds);
    return posts.filter((post) => ids.has(post.id));
  }, [posts, selectedIds]);
  const previewCount = useMemo(() => posts.filter(isPreview).length, [posts]);
  const previewSelected = selected.filter(isPreview).length;
  const needsUpdateCount = useMemo(() => {
    const staleCutoff = Date.now() - detailTtlDays * 24 * 60 * 60 * 1_000;
    return posts.filter((post) => {
      if (isPreview(post) || !post.last_detail_fetched_at) return true;
      const fetchedAt = Date.parse(post.last_detail_fetched_at);
      return !Number.isFinite(fetchedAt) || fetchedAt < staleCutoff;
    }).length;
  }, [detailTtlDays, posts]);
  const targetCount =
    target === 'all' ? posts.length : target === 'preview' ? previewCount : needsUpdateCount;
  const mutation = useMutation({
    mutationFn: apiService.startPostDetailUpdate,
    onSuccess: async (task) => {
      if (mode === 'selected') onSelectionChange([]);
      setMode(null);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.tasks, exact: true }),
        queryClient.invalidateQueries({ queryKey: queryKeys.task(task.id), exact: true }),
      ]);
      await onCreated(task);
    },
    onError: (error) =>
      message.error(error instanceof Error ? error.message : '帖子详情更新任务创建失败'),
  });

  useEffect(() => {
    if (mode !== 'batch') return;
    form.setFieldsValue({
      target: 'needs_update',
      max_posts: 300,
      batch_size: 10,
      post_delay_min_seconds: postDelayMin,
      post_delay_max_seconds: postDelayMax,
      batch_delay_min_seconds: batchDelayMin,
      batch_delay_max_seconds: batchDelayMax,
      consecutive_failure_limit: 5,
    });
  }, [batchDelayMax, batchDelayMin, form, mode, postDelayMax, postDelayMin]);

  const commonConfiguration = {
    scope,
    ...(scopeId === undefined ? {} : { scope_id: scopeId }),
    batch_size: 10,
    post_delay_min_seconds: postDelayMin,
    post_delay_max_seconds: postDelayMax,
    batch_delay_min_seconds: batchDelayMin,
    batch_delay_max_seconds: batchDelayMax,
    consecutive_failure_limit: 5,
  };
  const submitSelected = () => {
    if (!selectedIds.length) return;
    mutation.mutate({
      ...commonConfiguration,
      mode: 'selected',
      post_ids: selectedIds,
      max_posts: selectedIds.length,
    });
  };
  const submitBatch = async () => {
    const values = await form.validateFields();
    mutation.mutate({ ...commonConfiguration, ...values, mode: 'batch' });
  };
  const menuItems: MenuProps['items'] = [
    {
      key: 'selected',
      label: `获取选中帖子的详情${selectedIds.length ? `（${selectedIds.length} 篇）` : ''}`,
      disabled: selectedIds.length === 0,
    },
    { key: 'batch', label: '批量更新当前范围' },
  ];

  return (
    <>
      <Dropdown
        menu={{
          items: menuItems,
          onClick: ({ key }) => setMode(key === 'selected' ? 'selected' : 'batch'),
        }}
        trigger={['click']}
      >
        <Button icon={<FileSearchOutlined />} aria-label="更新帖子详情">
          更新帖子详情 <DownOutlined />
        </Button>
      </Dropdown>
      <Modal
        title="获取选中帖子的详情"
        open={mode === 'selected'}
        okText="创建更新任务"
        cancelText="取消"
        confirmLoading={mutation.isPending}
        onOk={submitSelected}
        onCancel={() => setMode(null)}
        destroyOnHidden
      >
        <Alert
          type="info"
          showIcon
          icon={<InfoCircleOutlined />}
          title={`已选择 ${selectedIds.length} 篇帖子`}
          description={`仅预览信息 ${previewSelected} 篇，已有详细信息 ${Math.max(0, selectedIds.length - previewSelected)} 篇。已有详细信息的帖子也会重新获取最新详情。`}
        />
      </Modal>
      <Modal
        title="批量更新帖子详情"
        open={mode === 'batch'}
        okText="创建批量更新任务"
        cancelText="取消"
        confirmLoading={mutation.isPending}
        onOk={() => void submitBatch()}
        onCancel={() => setMode(null)}
        destroyOnHidden
        width={720}
      >
        <Alert
          type="info"
          showIcon
          title="系统会在一个任务中固定目标清单并按批次低频执行"
          description="遇到登录或安全验证时任务会暂停，可从任务详情继续。"
          style={{ marginBottom: 20 }}
        />
        <Form form={form} layout="vertical">
          <Form.Item name="target" label="更新范围" rules={[{ required: true }]}>
            <Radio.Group>
              <Space orientation="vertical">
                <Radio value="needs_update">
                  需要补全或详情已过期的帖子（当前约 {needsUpdateCount} 篇）
                </Radio>
                <Radio value="preview">仅有预览信息的帖子（当前 {previewCount} 篇）</Radio>
                <Radio value="all">当前范围全部帖子（当前 {posts.length} 篇）</Radio>
              </Space>
            </Radio.Group>
          </Form.Item>
          <Alert
            type={targetCount ? 'success' : 'warning'}
            showIcon
            title={
              targetCount
                ? `当前条件约 ${targetCount} 篇；实际最多处理下方设置的数量。`
                : '当前条件下没有可更新帖子'
            }
            style={{ marginBottom: 20 }}
          />
          <Space align="start" size="middle" wrap>
            <Form.Item name="max_posts" label="最大处理帖子数" rules={[{ required: true }]}>
              <InputNumber min={1} max={500} precision={0} />
            </Form.Item>
            <Form.Item name="batch_size" label="批次大小" rules={[{ required: true }]}>
              <InputNumber min={1} max={50} precision={0} />
            </Form.Item>
            <Form.Item
              name="consecutive_failure_limit"
              label="连续失败阈值"
              rules={[{ required: true }]}
            >
              <InputNumber min={1} max={20} precision={0} />
            </Form.Item>
          </Space>
          <Typography.Title level={5}>安全间隔</Typography.Title>
          <Space align="start" size="middle" wrap>
            <Form.Item name="post_delay_min_seconds" label="帖子间隔最短秒数">
              <InputNumber min={0} max={3600} precision={0} />
            </Form.Item>
            <Form.Item name="post_delay_max_seconds" label="帖子间隔最长秒数">
              <InputNumber min={0} max={3600} precision={0} />
            </Form.Item>
            <Form.Item name="batch_delay_min_seconds" label="批次间隔最短秒数">
              <InputNumber min={0} max={3600} precision={0} />
            </Form.Item>
            <Form.Item name="batch_delay_max_seconds" label="批次间隔最长秒数">
              <InputNumber min={0} max={3600} precision={0} />
            </Form.Item>
          </Space>
        </Form>
      </Modal>
    </>
  );
}
