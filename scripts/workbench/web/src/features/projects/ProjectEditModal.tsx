import { Form, Input, Modal } from 'antd';
import type { Project } from '@/types';

export interface ProjectEditValues {
  name: string;
  description: string;
}

interface ProjectEditModalProps {
  project?: Pick<Project, 'id' | 'name' | 'description'>;
  open: boolean;
  saving: boolean;
  onCancel: () => void;
  onSave: (values: ProjectEditValues) => void;
}

export default function ProjectEditModal({
  project,
  open,
  saving,
  onCancel,
  onSave,
}: ProjectEditModalProps) {
  const [form] = Form.useForm<ProjectEditValues>();

  return (
    <Modal
      title="编辑项目"
      open={open}
      okText="保存修改"
      cancelText="取消"
      confirmLoading={saving}
      onCancel={onCancel}
      onOk={() => form.submit()}
      destroyOnHidden
    >
      <Form<ProjectEditValues>
        form={form}
        layout="vertical"
        requiredMark={false}
        initialValues={{
          name: project?.name ?? '',
          description: project?.description ?? '',
        }}
        onFinish={(values) =>
          onSave({
            name: values.name.trim(),
            description: values.description?.trim() ?? '',
          })
        }
      >
        <Form.Item
          name="name"
          label="项目名称"
          rules={[
            { required: true, whitespace: true, message: '请填写项目名称' },
            { max: 80, message: '项目名称最多 80 个字符' },
          ]}
        >
          <Input
            allowClear
            maxLength={80}
            showCount
            autoComplete="off"
            placeholder="请输入项目名称"
          />
        </Form.Item>
        <Form.Item name="description" label="项目说明">
          <Input.TextArea
            rows={5}
            maxLength={2000}
            showCount
            placeholder="记录项目目标、范围或后续分析方向"
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
