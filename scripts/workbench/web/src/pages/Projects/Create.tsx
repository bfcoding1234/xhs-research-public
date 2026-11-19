import { PageContainer, ProForm, ProFormText, ProFormTextArea } from '@ant-design/pro-components';
import { useQueryClient } from '@tanstack/react-query';
import { history } from '@umijs/max';
import { Alert, App, Card } from 'antd';
import { getErrorMessage } from '@/features/research';
import { apiService } from '@/services/api';
import { queryKeys } from '@/services/queryKeys';
interface ProjectFormValues {
  name: string;
  description?: string;
}

export default function CreateProjectPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  return (
    <PageContainer
      title="新建调研项目"
      subTitle="创建调研主题后，再在项目内维护关键词、作者和帖子"
      onBack={() => history.push('/projects')}
    >
      <Card style={{ maxWidth: 760 }}>
        <ProForm<ProjectFormValues>
          layout="vertical"
          submitter={{ searchConfig: { submitText: '创建项目' }, resetButtonProps: false }}
          onFinish={async (values) => {
            try {
              const project = await apiService.createProject({
                name: values.name.trim(),
                research_type: 'keyword',
                description: values.description?.trim(),
              });
              await queryClient.invalidateQueries({ queryKey: queryKeys.projects });
              message.success('项目已创建');
              history.push(`/projects/${project.id}/keywords`);
              return true;
            } catch (error) {
              message.error({ content: getErrorMessage(error), duration: 6 });
              return false;
            }
          }}
        >
          <Alert
            type="info"
            showIcon
            title="先建立调研主题，再逐步积累资料"
            description="创建项目不会自动发起采集任务。进入项目后可维护关键词、发起搜索，或关联已有帖子和作者。"
          />
          <ProFormText
            name="name"
            label="项目名称"
            placeholder="例如：AI 产品经理内容机会"
            rules={[
              { required: true, message: '请填写项目名称' },
              { max: 80, message: '项目名称最多 80 个字符' },
            ]}
          />
          <ProFormTextArea
            name="description"
            label="项目说明（选填）"
            placeholder="记录项目目标、范围或后续分析方向"
            fieldProps={{ rows: 4, maxLength: 2000, showCount: true }}
          />
        </ProForm>
      </Card>
    </PageContainer>
  );
}
