import { ModalForm, ProFormRadio } from '@ant-design/pro-components';
import { Alert, App, Form, Tag, Typography } from 'antd';
import { useEffect, useState } from 'react';
import { apiService } from '@/services/api';
import type { AppSettings, Project, ResearchType, TaskReceipt } from '@/types';
import {
  buildResearchConfiguration,
  defaultResearchValues,
  getErrorMessage,
  validateResearchConfiguration,
} from './configuration';
import ResearchFields from './ResearchFields';
import styles from './research.module.css';
import type { ResearchFormValues } from './types';

interface CreateResearchTaskModalProps {
  project: Project;
  settings: AppSettings;
  open: boolean;
  initialKeywords?: string[];
  onClose: () => void;
  onCreated: (task: TaskReceipt) => void | Promise<void>;
}

function creatableMode(mode: ResearchType): ResearchType {
  return mode === 'author' ? 'author' : 'keyword';
}

export default function CreateResearchTaskModal({
  project,
  settings,
  open,
  initialKeywords = [],
  onClose,
  onCreated,
}: CreateResearchTaskModalProps) {
  const { message } = App.useApp();
  const [form] = Form.useForm<ResearchFormValues>();
  const [mode, setMode] = useState<ResearchType>(creatableMode(project.research_type));

  useEffect(() => {
    if (!open) return;
    const nextMode = creatableMode(project.research_type);
    setMode(nextMode);
    form.resetFields();
    form.setFieldsValue({
      ...defaultResearchValues(settings),
      mode: nextMode,
      projectId: project.id,
      keywords: initialKeywords,
    });
  }, [form, initialKeywords, open, project.id, project.research_type, settings]);

  return (
    <ModalForm<ResearchFormValues>
      title="发起采集任务"
      open={open}
      form={form}
      width={880}
      layout="vertical"
      submitter={{
        searchConfig: { submitText: '发起任务', resetText: '取消' },
      }}
      modalProps={{
        destroyOnHidden: true,
        maskClosable: false,
        onCancel: onClose,
        styles: { body: { maxHeight: 'calc(100vh - 220px)', overflowY: 'auto' } },
      }}
      onFinish={async (values) => {
        try {
          const nextMode = values.mode ?? mode;
          const configuration = buildResearchConfiguration(values, nextMode, settings);
          validateResearchConfiguration(configuration, nextMode, settings);
          const task = await apiService.createTask(project.id, nextMode, configuration);
          onClose();
          await onCreated(task);
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
        title="项目关联任务"
        description="关键词命中的帖子会进入当前项目；作者主页采集到的帖子只保存到全局库，可按需再关联。"
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
        <Tag color="blue">关联项目：{project.name}</Tag>
        <ResearchFields
          mode={mode}
          settings={settings}
          form={form}
          projectId={project.id}
        />
      </div>
    </ModalForm>
  );
}
