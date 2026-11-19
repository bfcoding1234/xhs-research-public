import { MessageOutlined } from '@ant-design/icons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { history } from '@umijs/max';
import {
  Alert,
  App,
  Button,
  Form,
  InputNumber,
  Modal,
  Radio,
  Space,
  Switch,
  Typography,
} from 'antd';
import { useState } from 'react';
import TaskCreatedModal from '@/components/TaskCreatedModal';
import { apiService } from '@/services/api';
import { queryKeys } from '@/services/queryKeys';
import type {
  PostCommentCheckpoint,
  PostCommentCollectionConfiguration,
  TaskReceipt,
} from '@/types';
import { formatNumber } from '@/utils/format';

export interface CommentCollectionPost {
  id: number;
  note_id: string;
  title?: string;
  comments_count?: number | null;
}

export function defaultPostCommentCollectionConfiguration(
  checkpoint?: PostCommentCheckpoint | null,
): PostCommentCollectionConfiguration {
  const continueUnavailable =
    checkpoint?.status === 'exhausted' || checkpoint?.status === 'invalid';
  return {
    collection_mode: continueUnavailable ? 'refresh' : 'continue',
    requested_pages: 1,
    page_delay_min_seconds: 1,
    page_delay_max_seconds: 2,
    include_sub_comments: false,
    sub_comment_page_limit: 20,
  };
}

export function PostCommentQuickCollectionAction({
  post,
  checkpoint,
  disabled = false,
}: {
  post: CommentCollectionPost;
  checkpoint?: PostCommentCheckpoint | null;
  disabled?: boolean;
}) {
  const queryClient = useQueryClient();
  const mutation = useMutation<TaskReceipt, Error>({
    mutationFn: () =>
      apiService.startPostCommentCollection(
        post.id,
        defaultPostCommentCollectionConfiguration(checkpoint),
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.tasks }),
        queryClient.invalidateQueries({ queryKey: queryKeys.postComments(post.id) }),
      ]);
    },
  });

  return (
    <Button disabled={disabled} loading={mutation.isPending} onClick={() => mutation.mutate()}>
      快捷补充评论
    </Button>
  );
}

export default function PostCommentCollectionAction({
  post,
  buttonType = 'link',
  checkpoint,
}: {
  post: CommentCollectionPost;
  buttonType?: 'link' | 'default' | 'primary';
  checkpoint?: PostCommentCheckpoint | null;
}) {
  const [form] = Form.useForm<PostCommentCollectionConfiguration>();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [createdTask, setCreatedTask] = useState<TaskReceipt | null>(null);
  const includeSubComments = Form.useWatch('include_sub_comments', form) ?? false;
  const collectionMode = Form.useWatch('collection_mode', form) ?? 'continue';
  const continueUnavailable =
    checkpoint?.status === 'exhausted' || checkpoint?.status === 'invalid';
  const initialValues = defaultPostCommentCollectionConfiguration(checkpoint);
  const mutation = useMutation<TaskReceipt, Error, PostCommentCollectionConfiguration>({
    mutationFn: (configuration) => apiService.startPostCommentCollection(post.id, configuration),
    onSuccess: async (task) => {
      setOpen(false);
      setCreatedTask(task);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.tasks }),
        queryClient.invalidateQueries({ queryKey: queryKeys.postComments(post.id) }),
      ]);
    },
    onError: (error) =>
      message.error(error instanceof Error ? error.message : '评论采集任务创建失败'),
  });

  const openModal = () => {
    setOpen(true);
  };

  const submit = () => {
    form
      .validateFields()
      .then((values) =>
        mutation.mutate({
          ...values,
          sub_comment_page_limit: values.sub_comment_page_limit ?? 20,
        }),
      )
      .catch(() => undefined);
  };

  return (
    <>
      <Button icon={<MessageOutlined />} type={buttonType} onClick={openModal}>
        补充评论
      </Button>
      <Modal
        title="补充评论"
        open={open}
        okText="开始采集"
        cancelText="取消"
        confirmLoading={mutation.isPending}
        destroyOnHidden
        onCancel={() => setOpen(false)}
        onOk={submit}
      >
        <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
          <div>
            <Typography.Text strong>{post.title || post.note_id}</Typography.Text>
            <br />
            <Typography.Text type="secondary">
              平台显示 {formatNumber(post.comments_count)} 条评论 · 帖子 ID {post.note_id}
            </Typography.Text>
          </div>
          <Form form={form} layout="vertical" requiredMark={false} initialValues={initialValues}>
            <Form.Item name="collection_mode" label="采集方式" rules={[{ required: true }]}>
              <Radio.Group
                optionType="button"
                buttonStyle="solid"
                options={[
                  {
                    label: '继续补充',
                    value: 'continue',
                    disabled: continueUnavailable,
                    title:
                      checkpoint?.status === 'exhausted'
                        ? '已补充到平台当前末页'
                        : checkpoint?.status === 'invalid'
                          ? '续传位置已失效'
                          : undefined,
                  },
                  { label: '重新更新', value: 'refresh' },
                ]}
              />
            </Form.Item>
            <Form.Item
              name="requested_pages"
              label="本次抓取页数"
              rules={[{ required: true }, { type: 'number', min: 1, max: 20 }]}
            >
              <InputNumber aria-label="抓取页数" min={1} max={20} precision={0} />
            </Form.Item>
            <Space align="start" size="middle" wrap>
              <Form.Item
                name="page_delay_min_seconds"
                label="随机等待最短"
                rules={[{ required: true }, { type: 'number', min: 1, max: 60 }]}
              >
                <InputNumber aria-label="随机等待最短" min={1} max={60} />
              </Form.Item>
              <Form.Item
                name="page_delay_max_seconds"
                label="随机等待最长"
                dependencies={['page_delay_min_seconds']}
                rules={[
                  { required: true },
                  { type: 'number', min: 1, max: 60 },
                  ({ getFieldValue }) => ({
                    validator: async (_, value) => {
                      if (value >= getFieldValue('page_delay_min_seconds')) return;
                      throw new Error('最长等待不能小于最短等待');
                    },
                  }),
                ]}
              >
                <InputNumber aria-label="随机等待最长" min={1} max={60} />
              </Form.Item>
            </Space>
            <Form.Item
              name="include_sub_comments"
              label="抓取楼中楼"
              valuePropName="checked"
              extra="开启后会增加额外请求，仍按上方时间随机等待。"
            >
              <Switch checkedChildren="抓取" unCheckedChildren="不抓取" />
            </Form.Item>
            {includeSubComments ? (
              <Form.Item
                name="sub_comment_page_limit"
                label="楼中楼请求预算"
                rules={[{ required: true }, { type: 'number', min: 1, max: 100 }]}
                extra="达到预算后保留已抓取的回复，并标记为未完整。"
              >
                <InputNumber aria-label="楼中楼请求预算" min={1} max={100} precision={0} />
              </Form.Item>
            ) : null}
          </Form>
          <Alert
            showIcon
            type="info"
            title={collectionMode === 'continue' ? '从上次位置继续补充' : '从首页重新更新'}
            description={
              collectionMode === 'continue'
                ? `每页通常约 10 条一级评论。${checkpoint ? `已续传 ${checkpoint.completed_pages} 页，` : '尚未建立续传位置，'}本次成功后会保存新的续传位置。`
                : '幂等更新近期评论；有效的深度续传位置不会被回退。'
            }
          />
        </Space>
      </Modal>
      <TaskCreatedModal
        task={createdTask}
        onStay={() => setCreatedTask(null)}
        onView={(task) => {
          setCreatedTask(null);
          history.push(`/tasks/${task.id}`);
        }}
      />
    </>
  );
}
