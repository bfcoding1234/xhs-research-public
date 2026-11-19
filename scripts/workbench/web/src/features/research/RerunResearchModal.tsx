import { ModalForm, ProFormCheckbox } from '@ant-design/pro-components';
import { Alert, App, Descriptions, Form, Tag } from 'antd';
import { useEffect, useState } from 'react';
import { apiService } from '@/services/api';
import type { AppSettings, Author, Project, Task, TaskReceipt } from '@/types';
import { researchTypeLabels } from '@/utils/format';
import { isMyProject } from '@/utils/myProjects';
import {
  buildResearchConfiguration,
  getErrorMessage,
  researchValuesFromTask,
  validateResearchConfiguration,
} from './configuration';
import ResearchFields from './ResearchFields';
import styles from './research.module.css';
import type { ResearchFormValues } from './types';

export interface RerunResearchModalProps {
  project: Project;
  sourceTask: Task | null | undefined;
  settings: AppSettings;
  authors?: Author[];
  open: boolean;
  onClose: () => void;
  onCreated: (task: TaskReceipt) => void | Promise<void>;
}

export default function RerunResearchModal({
  project,
  sourceTask,
  settings,
  authors = [],
  open,
  onClose,
  onCreated,
}: RerunResearchModalProps) {
  const { message } = App.useApp();
  const [form] = Form.useForm<ResearchFormValues>();
  const [submitError, setSubmitError] = useState('');
  const mode = sourceTask?.mode && sourceTask.mode !== 'post'
    ? sourceTask.mode
    : project.research_type;
  const authorLimit = isMyProject(project) ? 1 : undefined;

  useEffect(() => {
    if (!open) return;
    setSubmitError('');
    form.resetFields();
    if (sourceTask) {
      form.setFieldsValue(researchValuesFromTask(sourceTask, settings));
    }
  }, [form, open, settings, sourceTask]);

  return (
    <ModalForm<ResearchFormValues>
      title="配置并更新调研"
      open={open}
      form={form}
      width={840}
      layout="vertical"
      submitter={{
        searchConfig: {
          submitText: '确认并开始',
          resetText: '取消',
        },
      }}
      modalProps={{
        destroyOnHidden: true,
        maskClosable: false,
        onCancel: onClose,
      }}
      onFinish={async (values) => {
        if (!sourceTask) {
          const errorMessage = '没有找到可作为更新基线的调研任务';
          setSubmitError(errorMessage);
          message.error(errorMessage);
          return false;
        }

        let task: TaskReceipt;
        try {
          const configuration = buildResearchConfiguration(values, mode, settings);
          validateResearchConfiguration(configuration, mode, settings);
          task = await apiService.rerunProject(project.id, sourceTask.id, configuration);
        } catch (error) {
          const errorMessage = getErrorMessage(error);
          setSubmitError(errorMessage);
          message.error(errorMessage);
          return false;
        }

        setSubmitError('');
        message.success('更新任务已创建');
        onClose();
        try {
          await onCreated(task);
        } catch {
          message.warning(`任务 ${task.id} 已创建，但未能自动打开详情，请前往任务中心查看`);
        }
        return true;
      }}
    >
      <Alert
        className={styles.modalIdentity}
        type="info"
        showIcon
        title="项目名称与调研类型保持不变"
        description={
          <Descriptions
            size="small"
            column={{ xs: 1, sm: 2 }}
            items={[
              { key: 'project', label: '项目', children: project.name },
              {
                key: 'mode',
                label: '类型',
                children: <Tag color="blue">{researchTypeLabels[mode]}</Tag>,
              },
            ]}
          />
        }
      />

      {!sourceTask ? (
        <Alert
          type="error"
          showIcon
          title="无法更新调研"
          description="当前项目没有可复用的历史调研任务，请先创建一轮调研。"
        />
      ) : (
        <>
          <ResearchFields
            mode={mode}
            settings={settings}
            form={form}
            candidateAuthors={authors}
            maxAuthors={authorLimit}
          />
          <ProFormCheckbox name="forceRefresh">
            强制刷新：忽略帖子详情与作者资料的有效期
          </ProFormCheckbox>
        </>
      )}

      {submitError ? (
        <Alert
          className={styles.submitError}
          type="error"
          showIcon
          title="更新任务未启动"
          description={submitError}
        />
      ) : null}
    </ModalForm>
  );
}
