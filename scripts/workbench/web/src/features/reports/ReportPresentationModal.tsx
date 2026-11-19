import { useMutation, useQueryClient } from '@tanstack/react-query';
import { App, Button, Form, Input, Modal, Select } from 'antd';
import { useEffect } from 'react';
import { apiService } from '@/services/api';
import { queryKeys } from '@/services/queryKeys';
import type {
  Report,
  ReportPresentationConfiguration,
  TaskReceipt,
} from '@/types';

export default function ReportPresentationModal({
  target,
  report,
  open,
  onClose,
  onCreated,
}: {
  target: { type: 'project' | 'author'; id: number };
  report?: Report;
  open: boolean;
  onClose: () => void;
  onCreated: (task: TaskReceipt) => void | Promise<void>;
}) {
  const [form] = Form.useForm<ReportPresentationConfiguration>();
  const queryClient = useQueryClient();
  const { message } = App.useApp();
  useEffect(() => {
    if (open && report) {
      form.setFieldsValue({
        title: `${report.title} 演示稿`,
        page_mode: 'standard',
        instructions: '',
      });
    }
  }, [form, open, report]);
  const mutation = useMutation({
    mutationFn: (values: ReportPresentationConfiguration) => {
      if (!report) throw new Error('源大模型报告不存在');
      return apiService.startReportPresentation(target, report.id, values);
    },
    onSuccess: (task) => {
      if (report) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.reportPresentations(target.type, target.id, report.id),
        });
      }
      onClose();
      void onCreated(task);
    },
    onError: (error) => message.error(error.message),
  });
  return (
    <Modal
      title="制作 HTML 演示稿"
      open={open}
      onCancel={onClose}
      footer={null}
      destroyOnHidden
      width={620}
    >
      <Form<ReportPresentationConfiguration>
        form={form}
        layout="vertical"
        onFinish={(values) => mutation.mutate(values)}
        style={{ marginTop: 16 }}
      >
        <Form.Item
          name="title"
          label="演示稿标题"
          rules={[
            { required: true, message: '请输入演示稿标题' },
            { max: 200, message: '演示稿标题最多 200 个字符' },
          ]}
        >
          <Input maxLength={200} showCount />
        </Form.Item>
        <Form.Item
          name="page_mode"
          label="篇幅"
          rules={[{ required: true, message: '请选择演示稿篇幅' }]}
        >
          <Select
            options={[
              { value: 'concise', label: '精简 · 6～8 页' },
              { value: 'standard', label: '标准 · 9～12 页' },
              { value: 'complete', label: '完整 · 13～16 页' },
            ]}
          />
        </Form.Item>
        <Form.Item
          name="instructions"
          label="补充要求"
          rules={[{ max: 1000, message: '补充要求最多 1000 个字符' }]}
          extra="可说明受众、汇报场景或希望重点强调的结论。"
        >
          <Input.TextArea rows={4} maxLength={1000} showCount />
        </Form.Item>
        <div className="action-row">
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" htmlType="submit" loading={mutation.isPending}>
            确认制作
          </Button>
        </div>
      </Form>
    </Modal>
  );
}
