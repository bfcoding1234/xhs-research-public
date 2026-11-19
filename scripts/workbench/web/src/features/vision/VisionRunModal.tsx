import { useMutation } from '@tanstack/react-query';
import { Alert, App, Button, Checkbox, Flex, Form, InputNumber, Modal, Radio, Select, Statistic } from 'antd';
import { useEffect } from 'react';
import { apiService } from '@/services/api';
import type {
  AppSettings,
  ImageScope,
  VisionConfiguration,
  VisionStatus,
  VisionTaskConfiguration,
  TaskReceipt,
} from '@/types';
import { expectedVisionCount } from '@/utils/format';

interface Values {
  processing_method: 'vision' | 'ocr';
  image_scopes: ImageScope[];
  mode: VisionConfiguration['mode'];
  ratio: number;
  minimum: number;
  maximum: number;
  batch: number;
}

export interface VisionTarget {
  type: 'project' | 'author';
  id: number;
  name: string;
}

export function toVisionTaskConfiguration(values: Values): VisionTaskConfiguration {
  const common = {
    processing_method: values.processing_method,
    image_scopes: values.image_scopes,
    mode: values.mode,
    vision_batch_size: values.batch,
  };
  if (values.mode === 'vision-all') return common;
  return {
    ...common,
    vision_ratio: values.ratio / 100,
    vision_count: values.minimum,
    vision_max_count: values.maximum,
  };
}

export default function VisionRunModal({
  target,
  status,
  settings,
  open,
  onClose,
  onCreated,
}: {
  target: VisionTarget;
  status?: VisionStatus;
  settings: AppSettings;
  open: boolean;
  onClose: () => void;
  onCreated: (task: TaskReceipt) => void | Promise<void>;
}) {
  const { message } = App.useApp();
  const [form] = Form.useForm<Values>();
  const processingMethod = Form.useWatch('processing_method', form) ?? 'ocr';
  const imageScopes = Form.useWatch('image_scopes', form) ?? ['cover'];
  const mode = Form.useWatch('mode', form);
  const ratio = Form.useWatch('ratio', form) ?? 0;
  const minimum = Form.useWatch('minimum', form) ?? 1;
  const maximum = Form.useWatch('maximum', form) ?? 1;
  const isOcr = processingMethod === 'ocr';
  const selectedScopeStatuses = imageScopes.map((scope) => (
    isOcr ? status?.ocr_scopes?.[scope] : status?.vision_scopes?.[scope]
  ));
  const pending = selectedScopeStatuses.reduce(
    (sum, value) => sum + (value?.pending_posts || 0), 0,
  );
  const availableImages = selectedScopeStatuses.reduce(
    (sum, value) => sum + (value?.available_images || 0), 0,
  );
  const completedImages = imageScopes.reduce(
    (sum, scope) => sum + (
      isOcr
        ? status?.ocr_scopes?.[scope]?.processed_images || 0
        : status?.vision_scopes?.[scope]?.analyzed_images || 0
    ), 0,
  );
  const providerAvailable = isOcr ? status?.ocr_provider_available : status?.provider_available;
  const previewConfiguration = {
    mode: mode || settings.vision_analysis_mode,
    vision_ratio: ratio / 100,
    vision_count: minimum,
    vision_max_count: maximum,
  };
  const preview = selectedScopeStatuses.reduce(
    (sum, value) => sum + expectedVisionCount(value?.pending_posts || 0, previewConfiguration),
    0,
  );
  useEffect(() => {
    if (!open) return;
    form.setFieldsValue({
      processing_method: 'ocr',
      image_scopes: ['cover'],
      mode: settings.vision_analysis_mode,
      ratio: Math.round((settings.vision_analysis_ratio ?? 0) * 100),
      minimum: settings.vision_analysis_count,
      maximum: settings.vision_analysis_max_count,
      batch: settings.vision_analysis_batch_size,
    });
  }, [open, settings, form]);
  const mutation = useMutation({
    mutationFn: (values: Values) =>
      target.type === 'author'
        ? apiService.startAuthorVision(target.id, toVisionTaskConfiguration(values))
        : apiService.startVision(target.id, toVisionTaskConfiguration(values)),
    onSuccess: (task) => {
      onClose();
      void onCreated(task);
    },
    onError: (error) => message.error(error.message),
  });
  const selective = mode !== 'vision-all';
  return (
    <Modal
      title={`补充图片理解 · ${target.name}`}
      open={open}
      onCancel={onClose}
      footer={null}
      destroyOnHidden
      width={720}
    >
      {status && !providerAvailable && (
        <Alert type="warning" showIcon title={isOcr ? 'RapidOCR 图片识字能力当前不可用' : 'Codex 图片理解能力当前不可用'} />
      )}
      <Flex className="stat-grid" style={{ marginBlock: 16 }}>
        {isOcr ? (
          <>
            <Statistic title="可处理图片" value={availableImages} />
            <Statistic title="OCR 已完成图片" value={completedImages} />
            <Statistic title="待处理帖子范围" value={pending} />
          </>
        ) : (
          <>
            <Statistic title="可处理图片" value={availableImages} />
            <Statistic title="已理解图片" value={completedImages} />
            <Statistic title="待处理帖子范围" value={pending} />
            <Statistic title="本次预计" value={preview} />
          </>
        )}
      </Flex>
      <Alert type="info" showIcon title={isOcr ? 'OCR 仅提取图片文字并写入媒体 OCR 字段。' : '本次参数只影响当前任务；已有报告不会被自动覆盖。'} />
      <Form<Values>
        form={form}
        layout="vertical"
        onFinish={(values) => mutation.mutate(values)}
        style={{ marginTop: 16 }}
      >
        <Form.Item name="processing_method" label="补充方式" rules={[{ required: true }]}>
          <Radio.Group>
            <Radio value="ocr">OCR 识图</Radio>
            <Radio value="vision">大模型理解</Radio>
          </Radio.Group>
        </Form.Item>
        <Form.Item
          name="image_scopes"
          label="图片范围"
          rules={[{ required: true, type: 'array', min: 1, message: '至少选择一种图片范围' }]}
        >
          <Checkbox.Group
            options={[
              { value: 'cover', label: '封面图' },
              { value: 'detail', label: '详情图片' },
            ]}
          />
        </Form.Item>
        <Form.Item name="mode" label="帖子选择" rules={[{ required: true }]}>
          <Select
            options={[
              { value: 'vision-selective', label: '选择性分析未处理图片' },
              { value: 'vision-all', label: '优先分析全部未处理图片' },
            ]}
          />
        </Form.Item>
        {selective && (
          <Flex gap="middle" wrap>
            <Form.Item
              name="ratio"
              label="选择比例（%）"
              rules={[
                { required: true, message: '请输入选择比例' },
                { type: 'number', min: 0, max: 100, message: '选择比例需要在 0–100 之间' },
              ]}
            >
              <InputNumber min={0} max={100} />
            </Form.Item>
            <Form.Item
              name="minimum"
              label="最低数量"
              rules={[
                { required: true, message: '请输入最低数量' },
                { type: 'number', min: 1, max: 300, message: '最低数量需要在 1–300 之间' },
              ]}
            >
              <InputNumber min={1} max={300} />
            </Form.Item>
            <Form.Item
              name="maximum"
              label="最高数量"
              dependencies={['minimum']}
              rules={[
                { required: true, message: '请输入最高数量' },
                { type: 'number', min: 1, max: 300, message: '最高数量需要在 1–300 之间' },
                ({ getFieldValue }) => ({
                  validator: (_, value) =>
                    Number(value) >= Number(getFieldValue('minimum'))
                      ? Promise.resolve()
                      : Promise.reject(new Error('最高数量不能小于最低数量')),
                }),
              ]}
            >
              <InputNumber min={1} max={300} />
            </Form.Item>
          </Flex>
        )}
        <Form.Item
          name="batch"
          label="每批帖子数"
          rules={[
            { required: true, message: '请输入每批帖子数' },
            { type: 'number', min: 1, max: 20, message: '每批帖子数需要在 1–20 之间' },
          ]}
        >
          <InputNumber min={1} max={20} />
        </Form.Item>
        <div className="action-row">
          <Button onClick={onClose}>取消</Button>
          <Button
            type="primary"
            htmlType="submit"
            loading={mutation.isPending}
            disabled={!providerAvailable || !pending}
          >
            确认并开始
          </Button>
        </div>
      </Form>
    </Modal>
  );
}
