import { IdcardOutlined, UserOutlined } from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { history } from '@umijs/max';
import { Alert, App, Button, Card, Divider, Form, Input, Select, Space, Typography } from 'antd';
import { useState } from 'react';
import { QueryError, QueryLoading } from '@/components/QueryState';
import TaskCreatedModal from '@/components/TaskCreatedModal';
import AuthorDetailPage from '@/pages/Authors/Detail';
import { apiService } from '@/services/api';
import { queryKeys } from '@/services/queryKeys';
import type { AppSettings, TaskReceipt } from '@/types';
import { MY_AUTHOR_ID_PATTERN, myAuthorOptions } from '@/utils/myAuthor';
import './index.css';

interface ExistingAuthorValues {
  author_id: number;
}

interface NewAuthorValues {
  external_author_id: string;
}

export default function MyPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [createdTask, setCreatedTask] = useState<TaskReceipt | null>(null);
  const settings = useQuery({
    queryKey: queryKeys.settings,
    queryFn: ({ signal }) => apiService.settings(signal),
  });
  const authors = useQuery({
    queryKey: queryKeys.authors,
    queryFn: ({ signal }) => apiService.authors(signal),
    enabled: settings.isSuccess && settings.data.my_author_id == null,
  });
  const setup = useMutation({
    mutationFn: apiService.setupMyAuthor,
    onSuccess: async (result) => {
      queryClient.setQueryData<AppSettings>(queryKeys.settings, (current) =>
        current ? { ...current, my_author_id: result.author_id } : current,
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.authors }),
        queryClient.invalidateQueries({ queryKey: queryKeys.tasks }),
      ]);
      if (result.task) {
        setCreatedTask(result.task);
      } else {
        message.success('个人作者已设置');
      }
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '初始化失败'),
  });

  if (settings.isPending) {
    return (
      <PageContainer title="个人">
        <Card>
          <QueryLoading rows={7} />
        </Card>
      </PageContainer>
    );
  }
  if (settings.isError) {
    return (
      <PageContainer title="个人">
        <QueryError error={settings.error} retry={() => void settings.refetch()} />
      </PageContainer>
    );
  }

  const authorId = settings.data.my_author_id ?? null;
  if (authorId === null) {
    const authorOptions = myAuthorOptions(authors.data ?? []);
    return (
      <PageContainer title="个人" subTitle="首次设置后，这里会固定展示你的个人作者详情">
        <Card className="my-project-setup">
          <Space orientation="vertical" size={4} className="my-project-setup-intro">
            <UserOutlined className="my-project-setup-icon" />
            <Typography.Title level={3}>先设置你的个人作者</Typography.Title>
            <Typography.Text type="secondary">
              已经采集过的作者可以直接选择；不在列表中时，输入作者 ID 初始化并抓取资料。
            </Typography.Text>
          </Space>

          <section className="my-project-setup-section">
            <Typography.Title level={5}>从已有作者中选择</Typography.Title>
            <Typography.Paragraph type="secondary">
              只保存配置，不会创建抓取任务。
            </Typography.Paragraph>
            {authors.isError ? (
              <QueryError error={authors.error} retry={() => void authors.refetch()} />
            ) : (
              <Form<ExistingAuthorValues>
                layout="vertical"
                requiredMark={false}
                onFinish={(values) => setup.mutate(values)}
              >
                <Form.Item
                  name="author_id"
                  label="已有作者"
                  rules={[{ required: true, message: '请选择一个作者' }]}
                  extra={
                    authors.data?.length === 0
                      ? '作者列表为空，请改用下方作者 ID 初始化。'
                      : undefined
                  }
                >
                  <Select
                    showSearch={{ optionFilterProp: 'label' }}
                    loading={authors.isPending}
                    placeholder="搜索昵称、小红书号或作者 ID"
                    options={authorOptions}
                    notFoundContent="没有匹配的作者"
                  />
                </Form.Item>
                <Button
                  type="primary"
                  htmlType="submit"
                  loading={setup.isPending}
                  disabled={authors.isPending || authorOptions.length === 0}
                >
                  选择这位作者
                </Button>
              </Form>
            )}
          </section>

          <Divider plain>或</Divider>

          <section className="my-project-setup-section">
            <Typography.Title level={5}>输入新的作者 ID</Typography.Title>
            <Alert
              className="my-project-setup-note"
              type="info"
              showIcon
              title="提交后会自动开始首次抓取"
              description="系统会获取作者基础信息和帖子预览，并将其保存为个人作者；不会逐篇打开帖子详情。"
            />
            <Form<NewAuthorValues>
              layout="vertical"
              requiredMark={false}
              onFinish={(values) =>
                setup.mutate({ external_author_id: values.external_author_id.trim() })
              }
            >
              <Form.Item
                name="external_author_id"
                label="作者 ID"
                rules={[
                  { required: true, message: '请输入作者 ID' },
                  {
                    pattern: MY_AUTHOR_ID_PATTERN,
                    message: '请输入 3～128 位字母、数字、下划线或连字符',
                  },
                ]}
              >
                <Input
                  allowClear
                  maxLength={128}
                  prefix={<IdcardOutlined />}
                  placeholder="例如：5f123abc_xyz"
                />
              </Form.Item>
              <Button type="primary" htmlType="submit" loading={setup.isPending}>
                设置并开始抓取
              </Button>
            </Form>
          </section>

          <Typography.Paragraph type="secondary" className="my-project-setup-footer">
            初始化后如需更换作者，请到“后台配置 → 个人”修改。
          </Typography.Paragraph>
        </Card>
      </PageContainer>
    );
  }

  return (
    <>
      <AuthorDetailPage
        authorId={authorId}
        routeBase="/my-projects"
        showBack={false}
        showBasicInfoUpdate
        showProjectAssociation={false}
        subTitle="个人 · 作者详情"
      />
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
