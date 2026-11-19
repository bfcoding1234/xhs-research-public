import {
  PageContainer,
  ProForm,
  ProFormRadio,
  ProFormSelect,
} from '@ant-design/pro-components';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { history, useLocation } from '@umijs/max';
import { Alert, App, Card, Form, Tag, Typography } from 'antd';
import { useMemo, useState } from 'react';
import { QueryError, QueryLoading } from '@/components/QueryState';
import TaskCreatedModal from '@/components/TaskCreatedModal';
import type { ResearchFormValues } from '@/features/research';
import {
  buildResearchConfiguration,
  defaultResearchValues,
  getErrorMessage,
  ResearchFields,
  validateResearchConfiguration,
} from '@/features/research';
import styles from '@/features/research/research.module.css';
import { apiService } from '@/services/api';
import { queryKeys } from '@/services/queryKeys';
import type { ResearchType, TaskReceipt } from '@/types';

function requestedMode(value: string | null): ResearchType {
  return value === 'author' ? value : 'keyword';
}

export default function CreateTaskPage() {
  const { search } = useLocation();
  const params = useMemo(() => new URLSearchParams(search), [search]);
  const rawProjectId = Number(params.get('project_id'));
  const fixedProjectId =
    Number.isInteger(rawProjectId) && rawProjectId > 0 ? rawProjectId : undefined;
  const [mode, setMode] = useState<ResearchType>(requestedMode(params.get('mode')));
  const [createdTask, setCreatedTask] = useState<TaskReceipt | null>(null);
  const [form] = Form.useForm<ResearchFormValues>();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: queryKeys.settings,
    queryFn: ({ signal }) => apiService.settings(signal),
  });
  const projects = useQuery({
    queryKey: queryKeys.projects,
    queryFn: ({ signal }) => apiService.projects(signal),
  });

  if (settings.isPending || projects.isPending) {
    return (
      <PageContainer title="发起采集任务">
        <Card>
          <QueryLoading rows={8} />
        </Card>
      </PageContainer>
    );
  }
  if (settings.isError) {
    return (
      <PageContainer title="发起采集任务">
        <QueryError error={settings.error} retry={() => settings.refetch()} />
      </PageContainer>
    );
  }
  if (projects.isError) {
    return (
      <PageContainer title="发起采集任务">
        <QueryError
          error={projects.error}
          retry={() => projects.refetch()}
        />
      </PageContainer>
    );
  }

  const associatedProject = fixedProjectId
    ? projects.data.find((project) => project.id === fixedProjectId)
    : undefined;
  if (fixedProjectId && !associatedProject) {
    return (
      <PageContainer title="发起采集任务" onBack={() => history.push('/tasks')}>
        <Alert
          showIcon
          type="error"
          title="关联项目不存在"
          description={`未找到项目 #${fixedProjectId}`}
        />
      </PageContainer>
    );
  }

  const defaults = defaultResearchValues(settings.data);
  const backPath = associatedProject ? `/projects/${associatedProject.id}/tasks` : '/tasks';
  return (
    <>
      <PageContainer
        title="发起采集任务"
        subTitle={
          associatedProject
            ? `任务将关联到项目「${associatedProject.name}」`
            : '任务可以独立运行，也可以选择关联项目'
        }
        onBack={() => history.push(backPath)}
      >
        <Card className={styles.formShell}>
          <ProForm<ResearchFormValues>
            form={form}
            layout="vertical"
            initialValues={{ ...defaults, mode, projectId: fixedProjectId }}
            submitter={{ searchConfig: { submitText: '发起任务' }, resetButtonProps: false }}
            onFinish={async (values) => {
              try {
                const nextMode = values.mode ?? mode;
                const configuration = buildResearchConfiguration(values, nextMode, settings.data);
                validateResearchConfiguration(configuration, nextMode, settings.data);
                const task = await apiService.createTask(values.projectId, nextMode, configuration);
                await Promise.all([
                  queryClient.invalidateQueries({ queryKey: queryKeys.tasks }),
                  values.projectId
                    ? queryClient.invalidateQueries({
                        queryKey: queryKeys.projectTasks(values.projectId),
                      })
                    : Promise.resolve(),
                ]);
                setCreatedTask(task);
                return true;
              } catch (error) {
                message.error({ content: getErrorMessage(error), duration: 6 });
                return false;
              }
            }}
          >
            <Alert
              className={styles.modeGuide}
              type="info"
              showIcon
              title={associatedProject ? '项目关联任务' : '独立采集任务'}
              description={
                associatedProject
                  ? '采集结果会进入全局数据，同时自动引用到当前项目。'
                  : '采集结果会进入全局帖子和作者库；稍后仍可将数据关联到任意项目。'
              }
            />
            <ProFormSelect
              name="projectId"
              label="关联项目（可选）"
              disabled={Boolean(fixedProjectId)}
              options={projects.data.map((project) => ({ value: project.id, label: project.name }))}
              fieldProps={{
                allowClear: !fixedProjectId,
                showSearch: { optionFilterProp: 'label' },
                placeholder: '不选择则作为独立任务运行',
              }}
            />
            <ProFormRadio.Group
              name="mode"
              label="采集类型"
              options={[
                { value: 'keyword', label: '关键词采集' },
                { value: 'author', label: '作者采集' },
              ]}
              fieldProps={{
                optionType: 'button',
                buttonStyle: 'solid',
                onChange: (event) => setMode(event.target.value as ResearchType),
              }}
              rules={[{ required: true, message: '请选择采集类型' }]}
            />
            <div className={styles.stepContent}>
              <Typography.Title level={4}>配置数据来源</Typography.Title>
              <Typography.Paragraph type="secondary">
                任务只负责采集数据。图片理解和报告仍在项目内基于项目数据单独发起。
              </Typography.Paragraph>
              {associatedProject ? (
                <Tag color="blue">关联项目：{associatedProject.name}</Tag>
              ) : null}
              <ResearchFields
                mode={mode}
                settings={settings.data}
                form={form}
              />
            </div>
          </ProForm>
        </Card>
      </PageContainer>
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
