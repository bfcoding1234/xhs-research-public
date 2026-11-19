import { useMutation } from '@tanstack/react-query';
import { Alert, App, Button, Checkbox, Form, Input, Modal, Radio, Select, Statistic, Switch } from 'antd';
import { useEffect, useState } from 'react';
import { apiService } from '@/services/api';
import type {
  ReportContextConfiguration,
  ReportGenerationConfiguration,
  Report,
  ReportStatus,
  TaskReceipt,
} from '@/types';
import {
  defaultReportContextConfiguration,
  reportPostSectionLabels,
  reportPostSelectionCount,
} from './reportContext';
import { formatDate } from '@/utils/format';

type Values = ReportGenerationConfiguration;

function initialContextConfiguration(): ReportContextConfiguration {
  return {
    authors: { ...defaultReportContextConfiguration.authors },
    posts: {
      ...defaultReportContextConfiguration.posts,
      sections: [...defaultReportContextConfiguration.posts.sections],
    },
  };
}

export default function ReportRunModal({
  target,
  status,
  reports = [],
  open,
  onClose,
  onCreated,
}: {
  target: { type: 'project' | 'author'; id: number; name: string };
  status?: ReportStatus;
  reports?: Report[];
  open: boolean;
  onClose: () => void;
  onCreated: (task: TaskReceipt) => void | Promise<void>;
}) {
  const [form] = Form.useForm<Values>();
  const [contextConfig, setContextConfig] = useState<ReportContextConfiguration>(
    initialContextConfiguration,
  );
  const [sources, setSources] = useState<Array<'data_summary' | 'current_detail'>>([
    'current_detail',
  ]);
  const summaries = reports.filter(
    (report) =>
      report.generator_type !== 'llm' &&
      report.report_type === 'data_summary' &&
      report.status !== 'generating',
  );
  const { message } = App.useApp();
  useEffect(() => {
    if (open) {
      const nextContextConfig = initialContextConfiguration();
      const nextSources: Array<'data_summary' | 'current_detail'> = summaries.length
        ? ['data_summary', 'current_detail']
        : ['current_detail'];
      form.setFieldsValue({
        title: `${target.name} 大模型报告`,
        instructions: '',
        sources: nextSources,
        data_summary_report_id: summaries[0]?.id,
        context_config: nextContextConfig,
      });
      setContextConfig(nextContextConfig);
      setSources(nextSources);
    }
  }, [open, target.name, form, reports]);
  const summaryEnabled = sources.includes('data_summary');
  const currentDetailEnabled = sources.includes('current_detail');
  const authorsEnabled = contextConfig.authors.enabled;
  const postsEnabled = contextConfig.posts.enabled;
  const selectedSections = contextConfig.posts.sections;
  const sectionsInvalid = postsEnabled && selectedSections.length === 0;
  const postCount = status?.post_count ?? 0;
  const mutation = useMutation({
    mutationFn: (values: Values) =>
      target.type === 'project'
        ? apiService.startReport(target.id, values)
        : apiService.startAuthorReport(target.id, values),
    onSuccess: (task) => {
      onClose();
      void onCreated(task);
    },
    onError: (error) => message.error(error.message),
  });
  return (
    <Modal
      title="生成大模型报告"
      open={open}
      onCancel={onClose}
      footer={null}
      destroyOnHidden
      width={760}
    >
      {status && !status.provider_available && (
        <Alert type="warning" showIcon title="Codex 报告能力当前不可用" />
      )}
      <div className="stat-grid" style={{ marginBlock: 16 }}>
        <Statistic title="帖子证据" value={status?.post_count || 0} />
        <Statistic title="作者证据" value={status?.author_count || 0} />
        <Statistic title="OCR 帖子" value={status?.ocr_post_count || 0} />
        <Statistic title="读图帖子" value={status?.vision_post_count || 0} />
      </div>
      <Alert
        type="info"
        showIcon
        title="报告使用任务启动时已经完成的证据快照；后续补充图片理解不会自动覆盖本报告。"
      />
      <Form<Values>
        form={form}
        layout="vertical"
        onFinish={(values) => mutation.mutate(values)}
        onValuesChange={(_changed, values) => {
          if (values.context_config) setContextConfig(values.context_config);
          if (values.sources) setSources(values.sources);
        }}
        style={{ marginTop: 16 }}
      >
        <Form.Item
          name="title"
          label="报告标题"
          rules={[
            { required: true, message: '请输入报告标题' },
            { max: 200, message: '报告标题最多 200 个字符' },
          ]}
        >
          <Input maxLength={200} showCount />
        </Form.Item>
        <Form.Item
          name="instructions"
          label="补充要求"
          rules={[{ max: 1000, message: '补充要求最多 1000 个字符' }]}
        >
          <Input.TextArea
            rows={4}
            maxLength={1000}
            showCount
            placeholder="可选：希望报告重点回答的问题"
          />
        </Form.Item>
        <Form.Item
          name="sources"
          label="数据来源"
          required
          rules={[{ required: true, type: 'array', min: 1, message: '至少选择一项数据来源' }]}
          extra="两项同时选择时，数据摘要负责统计口径，当前明细负责案例和原文证据。"
        >
          <Checkbox.Group
            options={[
              {
                value: 'data_summary',
                label: '引用数据摘要',
                disabled: summaries.length === 0,
              },
              { value: 'current_detail', label: '引用当前明细数据' },
            ]}
          />
        </Form.Item>
        {!summaries.length ? (
          <Alert type="info" showIcon title="还没有可引用的数据摘要，可先生成一份数据摘要。" />
        ) : null}
        {summaryEnabled ? (
          <Form.Item
            name="data_summary_report_id"
            label="数据摘要版本"
            rules={[{ required: true, message: '请选择数据摘要版本' }]}
            extra="该版本的统计数字、趋势和分布将作为本次报告的固定口径。"
          >
            <Select
              options={summaries.map((report) => ({
                value: report.id,
                label: `v${report.generator_version || report.version} · ${formatDate(report.generated_at)}`,
              }))}
            />
          </Form.Item>
        ) : null}
        {currentDetailEnabled ? <Form.Item label="当前明细数据" required>
          <div style={{ display: 'grid', gap: 12 }}>
            <div style={{ border: '1px solid var(--ant-color-border-secondary)', borderRadius: 8, padding: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
                <div>
                  <strong>引用作者</strong>
                  <div style={{ color: 'var(--ant-color-text-secondary)' }}>作者名称、简介、粉丝与互动等资料</div>
                </div>
                <Form.Item name={['context_config', 'authors', 'enabled']} valuePropName="checked" noStyle>
                  <Switch disabled={authorsEnabled && !postsEnabled} aria-label="引用作者" />
                </Form.Item>
              </div>
            </div>
            <div style={{ border: '1px solid var(--ant-color-border-secondary)', borderRadius: 8, padding: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
                <div>
                  <strong>引用帖子</strong>
                  <div style={{ color: 'var(--ant-color-text-secondary)' }}>按比例选样，并精确选择进入上下文的帖子内容</div>
                </div>
                <Form.Item name={['context_config', 'posts', 'enabled']} valuePropName="checked" noStyle>
                  <Switch disabled={postsEnabled && !authorsEnabled} aria-label="引用帖子" />
                </Form.Item>
              </div>
              {postsEnabled && (
                <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid var(--ant-color-border-secondary)' }}>
                  <Form.Item
                    name={['context_config', 'posts', 'selection_mode']}
                    label="帖子数量"
                    extra="篇数按任务启动时的帖子总数计算；较大比例会显著增加生成耗时。"
                    required
                  >
                    <Radio.Group
                      orientation="vertical"
                      options={[
                        {
                          value: 'representative',
                          label: `有代表性的帖子 · 20%，最多 20 篇（使用 ${reportPostSelectionCount(postCount, 'representative')} 篇）`,
                        },
                        {
                          value: 'expanded',
                          label: `更多帖子 · 50%（使用 ${reportPostSelectionCount(postCount, 'expanded')} 篇）`,
                        },
                        { value: 'all', label: `全部帖子 · 100%（使用 ${postCount} 篇）` },
                      ]}
                    />
                  </Form.Item>
                  <Form.Item
                    name={['context_config', 'posts', 'sections']}
                    label="帖子内容"
                    required
                    validateStatus={sectionsInvalid ? 'error' : undefined}
                    help={sectionsInvalid ? '引用帖子开启时至少选择一项帖子内容' : undefined}
                  >
                    <Checkbox.Group
                      options={Object.entries(reportPostSectionLabels).map(([value, label]) => ({ value, label }))}
                    />
                  </Form.Item>
                </div>
              )}
            </div>
          </div>
        </Form.Item> : null}
        <div className="action-row">
          <Button onClick={onClose}>取消</Button>
          <Button
            type="primary"
            htmlType="submit"
            loading={mutation.isPending}
            disabled={
              !status?.provider_available ||
              sources.length === 0 ||
              (currentDetailEnabled && (sectionsInvalid || (!postCount && !authorsEnabled)))
            }
          >
            确认生成
          </Button>
        </div>
      </Form>
    </Modal>
  );
}
