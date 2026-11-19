import {
  BranchesOutlined,
  CloudServerOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  PictureOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  SlidersOutlined,
  SyncOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import type { UseQueryResult } from '@tanstack/react-query';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Menu,
  Modal,
  Select,
  Space,
  Statistic,
  Tag,
  Typography,
} from 'antd';
import type { ReactNode } from 'react';
import { useEffect, useState } from 'react';
import { QueryError, QueryLoading } from '@/components/QueryState';
import { apiService } from '@/services/api';
import { queryKeys } from '@/services/queryKeys';
import type {
  AppSettings,
  CollectorCommand,
  ReportPromptTemplates,
  Stats,
  VisionConfiguration,
  VisionReasoningEffort,
} from '@/types';
import { formatBytes, formatNumber } from '@/utils/format';
import { myAuthorOptions } from '@/utils/myAuthor';
import { isLoopbackHost } from '@/utils/network';
import { DEFAULT_DEEP_RANGE_ERROR, defaultDeepFitsDiscovery } from '@/utils/settings';
import {
  activeSettingsSection,
  SETTINGS_SECTION_GROUPS,
  SETTINGS_SECTIONS,
  type SettingsSectionKey,
} from './settingsNavigation';
import {
  REPORT_PROMPT_TEMPLATE_MAX_LENGTH,
  REPORT_PROMPT_VARIABLES,
  validateReportPromptTemplate,
} from './reportPromptTemplates';
import './index.css';

type DefaultValues = Pick<AppSettings, 'default_discovery' | 'default_deep'>;
type SourceValues = Pick<
  AppSettings,
  | 'max_keywords_per_task'
  | 'max_authors_per_task'
  | 'default_keyword_author_limit'
  | 'xiaohongshu_cookie_source'
>;
type RefreshValues = Pick<
  AppSettings,
  | 'detail_ttl_days'
  | 'author_ttl_days'
  | 'max_author_notes'
  | 'post_delay_min_seconds'
  | 'post_delay_max_seconds'
  | 'batch_delay_min_seconds'
  | 'batch_delay_max_seconds'
>;
interface MyAuthorValues {
  my_author_id: number;
}

interface VisionFormValues {
  vision_analysis_mode: VisionConfiguration['mode'];
  vision_analysis_ratio_percent: number;
  vision_analysis_count: number;
  vision_analysis_max_count: number;
  vision_analysis_batch_size: number;
  vision_model: string;
  vision_reasoning_effort: VisionReasoningEffort;
  vision_timeout_seconds: number;
}

const reasoningEffortLabels: Record<VisionReasoningEffort, string> = {
  default: '使用模型默认值',
  low: '低',
  medium: '中',
  high: '高',
  xhigh: '极高',
  max: '最大',
  ultra: '超高',
};

const sectionIcons: Record<SettingsSectionKey, ReactNode> = {
  defaults: <SlidersOutlined />,
  source: <SafetyCertificateOutlined />,
  refresh: <SyncOutlined />,
  vision: <PictureOutlined />,
  'report-prompts': <FileTextOutlined />,
  routing: <BranchesOutlined />,
  me: <UserOutlined />,
  service: <CloudServerOutlined />,
  storage: <DatabaseOutlined />,
  'data-release': <SyncOutlined />,
};

const groupIcons: Record<string, ReactNode> = {
  research: <SlidersOutlined />,
  processing: <BranchesOutlined />,
  identity: <UserOutlined />,
  system: <CloudServerOutlined />,
};

function SettingsGroup({
  groupKey,
  title,
  description,
  children,
}: {
  groupKey: string;
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section className="settings-page-group" aria-labelledby={`settings-group-${groupKey}`}>
      <div className="settings-page-group-heading">
        <span className="settings-page-group-icon">{groupIcons[groupKey]}</span>
        <div>
          <Typography.Title id={`settings-group-${groupKey}`} level={4}>
            {title}
          </Typography.Title>
          <Typography.Text type="secondary">{description}</Typography.Text>
        </div>
      </div>
      <div className="settings-page-group-stack">{children}</div>
    </section>
  );
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '保存失败，请稍后重试';
}

function visionFormValues(settings: AppSettings): VisionFormValues {
  return {
    vision_analysis_mode: settings.vision_analysis_mode,
    vision_analysis_ratio_percent: Math.round(settings.vision_analysis_ratio * 100),
    vision_analysis_count: settings.vision_analysis_count,
    vision_analysis_max_count: settings.vision_analysis_max_count,
    vision_analysis_batch_size: settings.vision_analysis_batch_size,
    vision_model: settings.vision_model,
    vision_reasoning_effort: settings.vision_reasoning_effort,
    vision_timeout_seconds: settings.vision_timeout_seconds,
  };
}

function useSaveSettings(successText: string) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (values: Partial<AppSettings>) => apiService.updateSettings(values),
    onSuccess: (settings) => {
      queryClient.setQueryData(queryKeys.settings, settings);
      message.success(successText);
    },
    onError: (error) => message.error(errorMessage(error)),
  });
}

function ServiceSection({ settings }: { settings: AppSettings }) {
  const loopback = isLoopbackHost(settings.host);
  return (
    <Card
      id="settings-service"
      className="settings-page-section"
      title="服务与能力"
      extra={
        <Tag color={loopback ? 'success' : 'warning'}>
          {loopback ? '本机回环绑定' : '非回环网络绑定'}
        </Tag>
      }
    >
      {!loopback && (
        <Alert
          className="settings-page-section-note"
          type="warning"
          showIcon
          title="当前服务并非仅绑定本机回环地址"
          description={`监听 ${settings.host}:${settings.port} 可能允许其他设备连接；实际可访问范围取决于网络与防火墙配置。`}
        />
      )}
      <Descriptions
        column={1}
        items={[
          {
            key: 'endpoint',
            label: '监听地址',
            children: (
              <Space wrap>
                <Typography.Text code>{`${settings.host}:${settings.port}`}</Typography.Text>
                <Typography.Text type={loopback ? 'secondary' : 'warning'}>
                  {loopback ? '服务仅监听本机回环地址' : '非回环地址，可能对其他设备可见'}
                </Typography.Text>
              </Space>
            ),
          },
          {
            key: 'collector',
            label: '数据采集器',
            children: (
              <Space orientation="vertical" size="small">
                {(settings.collectors ?? []).map((collector) => (
                  <Space key={collector.id} wrap>
                    <Tag color={collector.available ? 'success' : 'default'}>
                      {collector.label}
                    </Tag>
                    <Tag>{collector.available ? '可用' : '未检测到'}</Tag>
                    <Typography.Text code copyable={{ text: collector.binary }}>
                      {collector.binary}
                    </Typography.Text>
                  </Space>
                ))}
              </Space>
            ),
          },
          {
            key: 'codex',
            label: 'Codex CLI',
            children: (
              <Typography.Text code copyable={{ text: settings.codex_bin }}>
                {settings.codex_bin}
              </Typography.Text>
            ),
          },
          {
            key: 'workers',
            label: '任务执行队列',
            children: (
              <Space separator={<Typography.Text type="secondary">·</Typography.Text>} wrap>
                <span>采集 {settings.research_workers}</span>
                <span>图片 {settings.vision_workers}</span>
                <span>报告 {settings.report_workers}</span>
              </Space>
            ),
          },
        ]}
      />
    </Card>
  );
}

type RouteDraft = Record<string, string[]>;

function routeDraft(settings: AppSettings, useDefaults = false): RouteDraft {
  return Object.fromEntries(
    (settings.capability_routes ?? []).map((route) => [
      route.capability,
      [...(useDefaults ? route.default_commands : route.commands)],
    ]),
  );
}

function commandOptions(commands: CollectorCommand[], capability: string) {
  return commands
    .filter((command) => command.capability === capability)
    .map((command) => ({
      value: command.id,
      label: `${command.label}${command.available ? '' : '（当前不可用）'}`,
      disabled: !command.available,
    }));
}

function CapabilityRoutingSection({ settings }: { settings: AppSettings }) {
  const commands = settings.collector_commands ?? [];
  const [draft, setDraft] = useState<RouteDraft>(() => routeDraft(settings));
  const save = useSaveSettings('原子能力路由已保存，新任务将使用新的指令顺序');

  useEffect(() => {
    setDraft(routeDraft(settings));
  }, [settings]);

  const updateDefault = (capability: string, command: string) => {
    setDraft((current) => ({
      ...current,
      [capability]: [command, ...(current[capability] ?? []).filter((value) => value !== command)],
    }));
  };
  const updateFallbacks = (capability: string, fallbacks: string[]) => {
    setDraft((current) => {
      const primary = current[capability]?.[0];
      return {
        ...current,
        [capability]: primary ? [primary, ...fallbacks] : fallbacks,
      };
    });
  };
  const routes = settings.capability_routes ?? [];
  const changed = JSON.stringify(draft) !== JSON.stringify(routeDraft(settings));

  return (
    <Card
      id="settings-routing"
      className="settings-page-section"
      title="原子能力路由"
      extra={<Tag color="processing">业务能力 → 采集指令</Tag>}
    >
      <Alert
        className="settings-page-section-note"
        type="info"
        showIcon
        title="任务只调用业务语义能力"
        description="每个能力的第一条指令是默认指令；失败后按配置顺序调用降级指令。保存只影响之后启动的任务，运行中的任务继续使用启动时的路由快照。"
      />
      <div className="settings-routing-list">
        {routes.map((route) => {
          const available = commandOptions(commands, route.capability);
          const selected = draft[route.capability] ?? route.commands;
          const primary = selected[0];
          const primaryCommand = commands.find((command) => command.id === primary);
          const fallbackOptions = available.filter((option) => option.value !== primary);
          return (
            <section className="settings-routing-item" key={route.capability}>
              <div className="settings-routing-heading">
                <div>
                  <Typography.Text strong>{route.label}</Typography.Text>
                  <Typography.Paragraph type="secondary">{route.description}</Typography.Paragraph>
                </div>
                <Typography.Text code>{route.capability}</Typography.Text>
              </div>
              {available.length ? <div className="settings-page-form-grid">
                <div>
                  <Typography.Text type="secondary">默认指令</Typography.Text>
                  <Select
                    aria-label={`${route.label}默认指令`}
                    value={primary}
                    options={available}
                    placeholder="选择默认指令"
                    onChange={(value) => updateDefault(route.capability, value)}
                  />
                </div>
                <div>
                  <Typography.Text type="secondary">降级指令（按选择顺序执行）</Typography.Text>
                  <Select
                    aria-label={`${route.label}降级指令`}
                    mode="multiple"
                    value={selected.slice(1)}
                    options={fallbackOptions}
                    placeholder="可选择多个降级指令"
                    onChange={(values) => updateFallbacks(route.capability, values)}
                  />
                </div>
              </div> : (
                <Alert
                  type="warning"
                  showIcon
                  title="暂未接入独立采集指令"
                  description="该业务能力已进入能力目录，后续采集器提供可独立调用的指令适配后即可在这里配置。"
                />
              )}
              {primaryCommand && (
                <Typography.Text className="settings-routing-command" code copyable={{ text: primaryCommand.instruction }}>
                  {primaryCommand.instruction}
                </Typography.Text>
              )}
            </section>
          );
        })}
      </div>
      <Space className="settings-routing-actions" wrap>
        <Button
          type="primary"
          loading={save.isPending}
          disabled={!changed || routes.some((route) => (
            commandOptions(commands, route.capability).some((option) => !option.disabled)
            && !(draft[route.capability]?.[0])
          ))}
          onClick={() => save.mutate({
            capability_routes: routes
              .filter((route) => (draft[route.capability]?.length ?? 0) > 0)
              .map((route) => ({
                ...route,
                commands: draft[route.capability] ?? route.commands,
              })),
          })}
        >
          保存能力路由
        </Button>
        <Button disabled={save.isPending} onClick={() => setDraft(routeDraft(settings, true))}>
          恢复系统默认顺序
        </Button>
      </Space>
    </Card>
  );
}

function MyAuthorSection({ settings }: { settings: AppSettings }) {
  const [form] = Form.useForm<MyAuthorValues>();
  const save = useSaveSettings('个人作者已保存');
  const authors = useQuery({
    queryKey: queryKeys.authors,
    queryFn: ({ signal }) => apiService.authors(signal),
  });

  useEffect(() => {
    form.setFieldsValue({ my_author_id: settings.my_author_id ?? undefined });
  }, [form, settings.my_author_id]);

  const submit = async (values: MyAuthorValues) => {
    try {
      const next = await save.mutateAsync(values);
      form.setFieldsValue({ my_author_id: next.my_author_id ?? undefined });
    } catch {
      // The mutation reports the API error through Ant Design's message API.
    }
  };

  return (
    <Card
      id="settings-me"
      className="settings-page-section"
      title="个人"
      extra={<Typography.Text type="secondary">固定展示为作者详情页</Typography.Text>}
    >
      <Alert
        className="settings-page-section-note"
        type="info"
        showIcon
        title="从已有作者中选择一位个人作者"
        description="保存后，“个人”模块会直接展示该作者的资料、帖子和报告；之后可以随时更换。"
      />
      {authors.isError ? (
        <QueryError error={authors.error} retry={() => void authors.refetch()} />
      ) : (
        <Form<MyAuthorValues>
          form={form}
          layout="vertical"
          requiredMark={false}
          onFinish={submit}
        >
          <Form.Item
            name="my_author_id"
            label="个人作者"
            rules={[{ required: true, message: '请选择一位个人作者' }]}
            extra={authors.data?.length === 0 ? '当前没有作者，请先发起作者调研。' : undefined}
          >
            <Select
              showSearch={{ optionFilterProp: 'label' }}
              loading={authors.isPending}
              placeholder="搜索昵称、小红书号或作者 ID"
              options={myAuthorOptions(authors.data ?? [])}
              notFoundContent="没有匹配的作者"
            />
          </Form.Item>
          <Button
            type="primary"
            htmlType="submit"
            loading={save.isPending}
            disabled={authors.isPending || authors.data?.length === 0}
          >
            保存个人作者
          </Button>
        </Form>
      )}
    </Card>
  );
}

function DefaultsSection({ settings }: { settings: AppSettings }) {
  const [form] = Form.useForm<DefaultValues>();
  const save = useSaveSettings('调研默认值已保存');

  useEffect(() => {
    form.setFieldsValue({
      default_discovery: settings.default_discovery,
      default_deep: settings.default_deep,
    });
  }, [form, settings.default_deep, settings.default_discovery]);

  const submit = async (values: DefaultValues) => {
    try {
      const next = await save.mutateAsync(values);
      form.setFieldsValue({
        default_discovery: next.default_discovery,
        default_deep: next.default_deep,
      });
    } catch {
      // The mutation reports the API error through Ant Design's message API.
    }
  };

  return (
    <Card
      id="settings-defaults"
      className="settings-page-section"
      title="调研默认值"
      extra={<Typography.Text type="secondary">新建项目时自动带入，仍可单独覆盖</Typography.Text>}
    >
      <Form
        form={form}
        layout="vertical"
        requiredMark={false}
        initialValues={{
          default_discovery: settings.default_discovery,
          default_deep: settings.default_deep,
        }}
        onFinish={submit}
      >
        <div className="settings-page-form-grid">
          <Form.Item
            name="default_discovery"
            label="发现数量"
            extra="作者和关键词列表最多尝试发现的帖子数，不设固定上限。"
            rules={[{ required: true, message: '请输入发现数量' }]}
          >
            <InputNumber min={1} precision={0} />
          </Form.Item>
          <Form.Item
            name="default_deep"
            label="深度分析数量"
            extra="建议保持 0；详情访问更慢，也更容易触发平台风控。"
            dependencies={['default_discovery']}
            rules={[
              { required: true, message: '请输入深度分析数量' },
              ({ getFieldValue }) => ({
                validator: async (_, deep: number | undefined) => {
                  const discovery = getFieldValue('default_discovery') as number | undefined;
                  if (deep === undefined || discovery === undefined) return;
                  if (!defaultDeepFitsDiscovery(deep, discovery)) {
                    throw new Error(DEFAULT_DEEP_RANGE_ERROR);
                  }
                },
              }),
            ]}
          >
            <InputNumber min={0} precision={0} />
          </Form.Item>
        </div>
        <Button type="primary" htmlType="submit" loading={save.isPending}>
          保存调研默认值
        </Button>
      </Form>
    </Card>
  );
}

function SourceSection({ settings }: { settings: AppSettings }) {
  const [form] = Form.useForm<SourceValues>();
  const save = useSaveSettings('任务来源保护已保存');

  useEffect(() => {
    form.setFieldsValue({
      max_keywords_per_task: settings.max_keywords_per_task,
      max_authors_per_task: settings.max_authors_per_task,
      default_keyword_author_limit: settings.default_keyword_author_limit,
      xiaohongshu_cookie_source: settings.xiaohongshu_cookie_source,
    });
  }, [
    form,
    settings.max_authors_per_task,
    settings.default_keyword_author_limit,
    settings.max_keywords_per_task,
    settings.xiaohongshu_cookie_source,
  ]);

  const submit = async (values: SourceValues) => {
    try {
      const next = await save.mutateAsync(values);
      form.setFieldsValue({
        max_keywords_per_task: next.max_keywords_per_task,
        max_authors_per_task: next.max_authors_per_task,
        default_keyword_author_limit: next.default_keyword_author_limit,
        xiaohongshu_cookie_source: next.xiaohongshu_cookie_source,
      });
    } catch {
      // The mutation reports the API error through Ant Design's message API.
    }
  };

  return (
    <Card
      id="settings-source"
      className="settings-page-section"
      title="任务来源保护"
      extra={<Tag color="warning">风控保护</Tag>}
    >
      <Alert
        className="settings-page-section-note"
        type="info"
        showIcon
        title="限制单次任务的来源规模，避免采集时间过长或触发平台风控。"
      />
      <Form
        form={form}
        layout="vertical"
        requiredMark={false}
        initialValues={{
          max_keywords_per_task: settings.max_keywords_per_task,
          max_authors_per_task: settings.max_authors_per_task,
          default_keyword_author_limit: settings.default_keyword_author_limit,
          xiaohongshu_cookie_source: settings.xiaohongshu_cookie_source,
        }}
        onFinish={submit}
      >
        <div className="settings-page-form-grid">
          <Form.Item
            name="max_keywords_per_task"
            label="单次关键词上限"
            extra="关键词采集会受到此上限约束。"
            rules={[{ required: true, message: '请输入单次关键词上限' }]}
          >
            <InputNumber min={1} max={20} precision={0} />
          </Form.Item>
          <Form.Item
            name="max_authors_per_task"
            label="单次作者上限"
            extra="作者主页 URL 和作者 ID 合并计数。"
            rules={[{ required: true, message: '请输入单次作者上限' }]}
          >
            <InputNumber min={1} max={20} precision={0} />
          </Form.Item>
          <Form.Item
            name="default_keyword_author_limit"
            label="关键词采集默认作者数"
            extra="关键词采集开启“采集相关作者”时，默认使用该数量；任务内仍可单独调整。"
            rules={[{ required: true, message: '请输入默认作者数' }]}
          >
            <InputNumber min={1} precision={0} />
          </Form.Item>
          <Form.Item
            name="xiaohongshu_cookie_source"
            label="小红书登录态来源"
            extra="每次 xiaohongshu-cli 采集前都会刷新并验证非访客登录态。请选择实际登录小红书的浏览器。"
            rules={[{ required: true, message: '请选择小红书登录态来源' }]}
          >
            <Select
              options={[
                { value: 'auto', label: '自动检测已登录浏览器' },
                { value: 'chrome', label: 'Google Chrome' },
                { value: 'edge', label: 'Microsoft Edge' },
                { value: 'brave', label: 'Brave' },
                { value: 'firefox', label: 'Firefox' },
                { value: 'safari', label: 'Safari' },
              ]}
            />
          </Form.Item>
        </div>
        <Button type="primary" htmlType="submit" loading={save.isPending}>
          保存任务来源保护
        </Button>
      </Form>
    </Card>
  );
}

function VisionSection({ settings }: { settings: AppSettings }) {
  const [form] = Form.useForm<VisionFormValues>();
  const save = useSaveSettings('图片理解设置已保存');
  const modelCatalog = useQuery({
    queryKey: queryKeys.visionModels,
    queryFn: ({ signal }) => apiService.visionModels(signal),
    staleTime: 60_000,
  });
  const mode = Form.useWatch('vision_analysis_mode', form) ?? settings.vision_analysis_mode;
  const model = Form.useWatch('vision_model', form) ?? settings.vision_model;
  const selectedModel = modelCatalog.data?.models.find((item) => item.id === model);
  const modelOptions = [
    { value: '', label: '跟随 Codex 默认模型' },
    ...(modelCatalog.data?.models ?? []).map((item) => ({
      value: item.id,
      label: item.label === item.id ? item.id : `${item.label}（${item.id}）`,
    })),
  ];
  if (settings.vision_model && !modelOptions.some((item) => item.value === settings.vision_model)) {
    modelOptions.push({
      value: settings.vision_model,
      label: `${settings.vision_model}（当前已保存，目录中不可用）`,
    });
  }
  const reasoningOptions = [
    { value: 'default', label: reasoningEffortLabels.default },
    ...(selectedModel?.reasoning_efforts ?? []).map((effort) => ({
      value: effort,
      label: reasoningEffortLabels[effort],
    })),
  ];

  useEffect(() => {
    form.setFieldsValue(visionFormValues(settings));
  }, [
    form,
    settings.vision_analysis_batch_size,
    settings.vision_analysis_count,
    settings.vision_analysis_max_count,
    settings.vision_analysis_mode,
    settings.vision_analysis_ratio,
    settings.vision_model,
    settings.vision_reasoning_effort,
    settings.vision_timeout_seconds,
  ]);

  const submit = async (values: VisionFormValues) => {
    const payload: Partial<AppSettings> = {
      vision_analysis_mode: values.vision_analysis_mode,
      vision_analysis_batch_size: values.vision_analysis_batch_size,
      vision_model: values.vision_model,
      vision_reasoning_effort: values.vision_reasoning_effort,
      vision_timeout_seconds: values.vision_timeout_seconds,
    };
    if (values.vision_analysis_mode === 'vision-selective') {
      payload.vision_analysis_ratio = values.vision_analysis_ratio_percent / 100;
      payload.vision_analysis_count = values.vision_analysis_count;
      payload.vision_analysis_max_count = values.vision_analysis_max_count;
    }
    try {
      const next = await save.mutateAsync(payload);
      form.setFieldsValue(visionFormValues(next));
    } catch {
      // The mutation reports the API error through Ant Design's message API.
    }
  };

  return (
    <Card
      id="settings-vision"
      className="settings-page-section"
      title="图片理解"
      extra={<Typography.Text type="secondary">普通调研始终只执行 OCR</Typography.Text>}
    >
      <Form
        form={form}
        layout="vertical"
        requiredMark={false}
        initialValues={visionFormValues(settings)}
        onFinish={submit}
      >
        <Typography.Title level={5}>模型调用</Typography.Title>
        <div className="settings-page-form-grid settings-page-form-grid-three">
          <Form.Item
            name="vision_model"
            label="图片理解模型"
            extra="模型来自本机 Codex 目录；留空时跟随 Codex 当前默认模型。"
            rules={[{ required: false }]}
          >
            <Select
              options={modelOptions}
              loading={modelCatalog.isLoading}
              showSearch={{ optionFilterProp: 'label' }}
              onChange={(value: string) => {
                const selected = modelCatalog.data?.models.find((item) => item.id === value);
                const currentEffort = form.getFieldValue('vision_reasoning_effort');
                if (
                  !value ||
                  (currentEffort !== 'default' && !selected?.reasoning_efforts.includes(currentEffort))
                ) {
                  form.setFieldValue('vision_reasoning_effort', 'default');
                }
              }}
            />
          </Form.Item>
          <Form.Item
            name="vision_reasoning_effort"
            label="推理强度"
            extra="可选值会随所选模型变化。"
            rules={[{ required: true, message: '请选择推理强度' }]}
          >
            <Select options={reasoningOptions} disabled={!model || !selectedModel} />
          </Form.Item>
          <Form.Item
            name="vision_timeout_seconds"
            label="调用超时"
            extra="单次 Codex 图片理解调用的最长等待时间。"
            rules={[{ required: true, message: '请输入调用超时' }]}
          >
            <InputNumber min={60} max={3600} precision={0} suffix="秒" />
          </Form.Item>
        </div>
        {modelCatalog.data && !modelCatalog.data.available && (
          <Alert
            className="settings-page-section-note"
            type="warning"
            showIcon
            title="暂时无法读取 Codex 图片模型目录"
            description={`${modelCatalog.data.error}。仍可切回“跟随 Codex 默认模型”并保存。`}
          />
        )}

        <Typography.Title level={5}>任务选择</Typography.Title>
        <div className="settings-page-form-grid">
          <Form.Item
            name="vision_analysis_mode"
            label="处理范围"
            extra="每次只处理尚无当前版本结果的图片。"
            rules={[{ required: true, message: '请选择处理范围' }]}
          >
            <Select
              options={[
                { value: 'vision-selective', label: '选择性分析未处理图片' },
                { value: 'vision-all', label: '分析全部未处理图片' },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="vision_analysis_batch_size"
            label="每批帖子数"
            extra="同一批帖子共用一次 Codex 图片理解调用。"
            rules={[{ required: true, message: '请输入每批帖子数' }]}
          >
            <InputNumber min={1} max={20} precision={0} />
          </Form.Item>
        </div>

        {mode === 'vision-selective' ? (
          <div className="settings-page-form-grid settings-page-form-grid-three">
            <Form.Item
              name="vision_analysis_ratio_percent"
              label="选择比例"
              extra="按项目中待处理图片帖子的比例计算。"
              rules={[{ required: true, message: '请输入选择比例' }]}
            >
              <InputNumber min={0} max={100} precision={0} suffix="%" />
            </Form.Item>
            <Form.Item
              name="vision_analysis_count"
              label="最低处理数量"
              extra="与比例换算结果取较大值。"
              rules={[{ required: true, message: '请输入最低处理数量' }]}
            >
              <InputNumber min={1} max={300} precision={0} />
            </Form.Item>
            <Form.Item
              name="vision_analysis_max_count"
              label="最高处理数量"
              extra="单次选择性分析不会超过此数量。"
              dependencies={['vision_analysis_count', 'vision_analysis_mode']}
              rules={[
                { required: true, message: '请输入最高处理数量' },
                ({ getFieldValue }) => ({
                  validator: async (_, maximum: number | undefined) => {
                    if (getFieldValue('vision_analysis_mode') !== 'vision-selective') return;
                    const minimum = Number(getFieldValue('vision_analysis_count'));
                    if (maximum !== undefined && Number(maximum) < minimum) {
                      throw new Error('最高处理数量不能小于最低处理数量');
                    }
                  },
                }),
              ]}
            >
              <InputNumber min={1} max={300} precision={0} />
            </Form.Item>
          </div>
        ) : (
          <Alert
            className="settings-page-section-note"
            type="info"
            showIcon
            title="全部模式会处理所有待处理图片，因此不需要比例和数量边界。"
          />
        )}

        <Button type="primary" htmlType="submit" loading={save.isPending}>
          保存图片理解设置
        </Button>
      </Form>
    </Card>
  );
}

function PromptVariableHelp({ kind }: { kind: keyof ReportPromptTemplates }) {
  return (
    <div className="settings-prompt-variables">
      <Typography.Text type="secondary">可用变量：</Typography.Text>
      <Space size={[8, 4]} wrap>
        {REPORT_PROMPT_VARIABLES[kind].map(([name, description]) => {
          const token = `{{${name}}}`;
          return (
            <Typography.Text key={name} type="secondary">
              <Typography.Text code copyable={{ text: token }}>
                {token}
              </Typography.Text>{' '}
              {description}
            </Typography.Text>
          );
        })}
      </Space>
    </div>
  );
}

function ReportPromptsSection({ settings }: { settings: AppSettings }) {
  const [form] = Form.useForm<ReportPromptTemplates>();
  const { message } = App.useApp();
  const save = useSaveSettings('报告提示词已保存，新报告任务将使用这套配置');

  useEffect(() => {
    form.setFieldsValue(settings.report_prompt_templates);
  }, [form, settings.report_prompt_templates]);

  const submit = async (values: ReportPromptTemplates) => {
    try {
      const next = await save.mutateAsync({ report_prompt_templates: values });
      form.setFieldsValue(next.report_prompt_templates);
    } catch {
      // The mutation reports the API error through Ant Design's message API.
    }
  };

  const promptRules = (kind: keyof ReportPromptTemplates) => [
    {
      validator: async (_: unknown, value: string | undefined) => {
        const error = validateReportPromptTemplate(kind, value);
        if (error) throw new Error(error);
      },
    },
  ];

  return (
    <Card
      id="settings-report-prompts"
      className="settings-page-section"
      title="大模型报告提示词"
      extra={
        <Typography.Text
          type="secondary"
          code
          copyable={{ text: settings.report_prompt_template_hash }}
        >
          {settings.report_prompt_template_hash.slice(0, 12)}
        </Typography.Text>
      }
    >
      <Alert
        className="settings-page-section-note"
        type="info"
        showIcon
        title="保存后只影响新创建的报告任务；已创建、运行中和历史报告继续使用各自的提示词快照。"
      />
      <Form
        form={form}
        layout="vertical"
        requiredMark={false}
        initialValues={settings.report_prompt_templates}
        onFinish={submit}
      >
        <Form.Item
          name="chunk"
          label="分批分析提示词"
          extra={<PromptVariableHelp kind="chunk" />}
          rules={promptRules('chunk')}
        >
          <Input.TextArea
            className="settings-prompt-editor"
            rows={12}
            maxLength={REPORT_PROMPT_TEMPLATE_MAX_LENGTH}
            showCount
          />
        </Form.Item>
        <Form.Item
          name="final"
          label="最终报告提示词"
          extra={<PromptVariableHelp kind="final" />}
          rules={promptRules('final')}
        >
          <Input.TextArea
            className="settings-prompt-editor"
            rows={16}
            maxLength={REPORT_PROMPT_TEMPLATE_MAX_LENGTH}
            showCount
          />
        </Form.Item>
        <Space wrap>
          <Button type="primary" htmlType="submit" loading={save.isPending}>
            保存提示词
          </Button>
          <Button
            disabled={save.isPending}
            onClick={() => {
              form.setFieldsValue(settings.report_prompt_defaults);
              void message.info('已恢复系统默认内容，点击“保存提示词”后生效');
            }}
          >
            恢复系统默认
          </Button>
        </Space>
      </Form>
    </Card>
  );
}

function RefreshSection({ settings }: { settings: AppSettings }) {
  const [form] = Form.useForm<RefreshValues>();
  const save = useSaveSettings('刷新策略已保存');

  useEffect(() => {
    form.setFieldsValue({
      detail_ttl_days: settings.detail_ttl_days,
      author_ttl_days: settings.author_ttl_days,
      max_author_notes: settings.max_author_notes,
      post_delay_min_seconds: settings.post_delay_min_seconds,
      post_delay_max_seconds: settings.post_delay_max_seconds,
      batch_delay_min_seconds: settings.batch_delay_min_seconds,
      batch_delay_max_seconds: settings.batch_delay_max_seconds,
    });
  }, [
    form,
    settings.author_ttl_days,
    settings.batch_delay_max_seconds,
    settings.batch_delay_min_seconds,
    settings.detail_ttl_days,
    settings.max_author_notes,
    settings.post_delay_max_seconds,
    settings.post_delay_min_seconds,
  ]);

  const submit = async (values: RefreshValues) => {
    try {
      const next = await save.mutateAsync(values);
      form.setFieldsValue({
        detail_ttl_days: next.detail_ttl_days,
        author_ttl_days: next.author_ttl_days,
        max_author_notes: next.max_author_notes,
        post_delay_min_seconds: next.post_delay_min_seconds,
        post_delay_max_seconds: next.post_delay_max_seconds,
        batch_delay_min_seconds: next.batch_delay_min_seconds,
        batch_delay_max_seconds: next.batch_delay_max_seconds,
      });
    } catch {
      // The mutation reports the API error through Ant Design's message API.
    }
  };

  return (
    <Card
      id="settings-refresh"
      className="settings-page-section"
      title="刷新策略"
      extra={<Typography.Text type="secondary">列表字段仍会在每次任务中更新</Typography.Text>}
    >
      <Form
        form={form}
        layout="vertical"
        requiredMark={false}
        initialValues={{
          detail_ttl_days: settings.detail_ttl_days,
          author_ttl_days: settings.author_ttl_days,
          max_author_notes: settings.max_author_notes,
          post_delay_min_seconds: settings.post_delay_min_seconds,
          post_delay_max_seconds: settings.post_delay_max_seconds,
          batch_delay_min_seconds: settings.batch_delay_min_seconds,
          batch_delay_max_seconds: settings.batch_delay_max_seconds,
        }}
        onFinish={submit}
      >
        <div className="settings-page-form-grid settings-page-form-grid-three">
          <Form.Item
            name="detail_ttl_days"
            label="帖子详情有效期（天）"
            extra="有效期内不重复读取已成功获取的详情。"
            rules={[{ required: true, message: '请输入帖子详情有效期' }]}
          >
            <InputNumber min={1} max={365} precision={0} />
          </Form.Item>
          <Form.Item
            name="author_ttl_days"
            label="作者资料有效期（天）"
            extra="有效期内复用粉丝、简介等扩展字段。"
            rules={[{ required: true, message: '请输入作者资料有效期' }]}
          >
            <InputNumber min={1} max={365} precision={0} />
          </Form.Item>
          <Form.Item
            name="max_author_notes"
            label="作者采集硬上限"
            extra="即使任务填写更大值，也会截断到此上限；该值本身不设固定上限。"
            rules={[{ required: true, message: '请输入作者采集硬上限' }]}
          >
            <InputNumber min={1} precision={0} />
          </Form.Item>
        </div>
        <Typography.Title level={5}>帖子详情批量更新安全间隔</Typography.Title>
        <Typography.Paragraph type="secondary">
          作为新建帖子详情更新任务的默认值；创建任务时仍可临时调整。
        </Typography.Paragraph>
        <div className="settings-page-form-grid settings-page-form-grid-four">
          <Form.Item
            name="post_delay_min_seconds"
            label="帖子间隔最短秒数"
            dependencies={['post_delay_max_seconds']}
            rules={[
              { required: true, message: '请输入帖子间隔最短秒数' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  const maximum = Number(getFieldValue('post_delay_max_seconds'));
                  return Number(value) <= maximum
                    ? Promise.resolve()
                    : Promise.reject(new Error('最短秒数不能大于最长秒数'));
                },
              }),
            ]}
          >
            <InputNumber min={0} max={3600} precision={0} />
          </Form.Item>
          <Form.Item
            name="post_delay_max_seconds"
            label="帖子间隔最长秒数"
            rules={[{ required: true, message: '请输入帖子间隔最长秒数' }]}
          >
            <InputNumber min={0} max={3600} precision={0} />
          </Form.Item>
          <Form.Item
            name="batch_delay_min_seconds"
            label="批次间隔最短秒数"
            dependencies={['batch_delay_max_seconds']}
            rules={[
              { required: true, message: '请输入批次间隔最短秒数' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  const maximum = Number(getFieldValue('batch_delay_max_seconds'));
                  return Number(value) <= maximum
                    ? Promise.resolve()
                    : Promise.reject(new Error('最短秒数不能大于最长秒数'));
                },
              }),
            ]}
          >
            <InputNumber min={0} max={3600} precision={0} />
          </Form.Item>
          <Form.Item
            name="batch_delay_max_seconds"
            label="批次间隔最长秒数"
            rules={[{ required: true, message: '请输入批次间隔最长秒数' }]}
          >
            <InputNumber min={0} max={3600} precision={0} />
          </Form.Item>
        </div>
        <Button type="primary" htmlType="submit" loading={save.isPending}>
          保存刷新策略
        </Button>
      </Form>
    </Card>
  );
}

function StorageSection({
  settings,
  stats,
}: {
  settings: AppSettings;
  stats: UseQueryResult<Stats, Error>;
}) {
  return (
    <Card
      id="settings-storage"
      className="settings-page-section"
      title="存储"
      extra={<Typography.Text type="secondary">全局主数据去重复用</Typography.Text>}
    >
      {stats.isError && !stats.data ? (
        <QueryError error={stats.error} retry={() => void stats.refetch()} />
      ) : stats.isPending || !stats.data ? (
        <QueryLoading rows={4} />
      ) : (
        <>
          <div className="settings-page-stat-grid">
            <Statistic title="项目" value={formatNumber(stats.data.projects)} />
            <Statistic title="全局帖子" value={formatNumber(stats.data.global_posts)} />
            <Statistic title="全局作者" value={formatNumber(stats.data.global_authors)} />
            <Statistic title="读图结果" value={formatNumber(stats.data.vision_analyses)} />
          </div>
          <Descriptions
            className="settings-page-storage-detail"
            column={1}
            items={[
              {
                key: 'dir',
                label: '数据目录',
                children: (
                  <Typography.Text code copyable={{ text: settings.data_dir }}>
                    {settings.data_dir}
                  </Typography.Text>
                ),
              },
              {
                key: 'database',
                label: '数据库',
                children: `${formatNumber(stats.data.tasks)} 个任务 · ${formatNumber(stats.data.reports)} 个报告版本 · ${formatBytes(stats.data.database_bytes)}`,
              },
              {
                key: 'media',
                label: '本地媒体',
                children: `${formatNumber(stats.data.downloaded_media)} / ${formatNumber(stats.data.media_assets)} 个媒体条目已下载 · ${formatBytes(stats.data.media_bytes)}`,
              },
            ]}
          />
        </>
      )}
    </Card>
  );
}

function DataReleaseSection({ settings }: { settings: AppSettings }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const isDevelopment = settings.data_dir.endsWith('-develop');
  const preview = useQuery({
    queryKey: ['data-release', 'preview'],
    queryFn: ({ signal }) => apiService.dataReleasePreview(signal),
    enabled: isDevelopment,
  });
  const publish = useMutation({
    mutationFn: apiService.publishDataRelease,
    onSuccess: async (result) => {
      message.success(`已发布到线上：${result.release_id}`);
      setConfirmOpen(false);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['data-release'] }),
        queryClient.invalidateQueries({ queryKey: queryKeys.stats }),
      ]);
    },
    onError: (error) => message.error(errorMessage(error)),
  });
  const counts = preview.data?.source_counts ?? {};

  return (
    <Card
      id="settings-data-release"
      className="settings-page-section"
      title="发布到线上"
      extra={<Tag color={isDevelopment ? 'processing' : 'default'}>{isDevelopment ? '开发版' : '线上版'}</Tag>}
    >
      {!isDevelopment ? (
        <Alert type="info" showIcon title="仅开发版可发起数据发布" description="线上版只接收已确认的数据，不会将本地采集结果回写到开发版。" />
      ) : preview.isError ? (
        <QueryError error={preview.error} retry={() => void preview.refetch()} />
      ) : preview.isPending || !preview.data ? (
        <QueryLoading rows={3} />
      ) : (
        <>
          <Alert
            className="settings-page-section-note"
            type={preview.data.can_publish ? 'info' : 'warning'}
            showIcon
            title={preview.data.can_publish ? '可发布：两端没有活跃任务' : '暂不能发布：请先等待活跃任务结束'}
            description={`目标线上数据目录：${preview.data.target_data_dir}`}
          />
          <div className="settings-page-stat-grid">
            <Statistic title="作者" value={formatNumber(counts.authors ?? 0)} />
            <Statistic title="帖子" value={formatNumber(counts.posts ?? 0)} />
            <Statistic title="项目" value={formatNumber(counts.projects ?? 0)} />
            <Statistic title="本地媒体" value={formatNumber(counts.media ?? 0)} />
          </div>
          <Typography.Paragraph type="secondary">
            {preview.data.rules.join(' ')}
          </Typography.Paragraph>
          <Button type="primary" disabled={!preview.data.can_publish} onClick={() => setConfirmOpen(true)}>
            预览确认后发布
          </Button>
          <Modal
            title="确认发布开发数据到线上"
            open={confirmOpen}
            okText="确认发布"
            cancelText="取消"
            confirmLoading={publish.isPending}
            onCancel={() => setConfirmOpen(false)}
            onOk={() => publish.mutate()}
          >
            <Typography.Paragraph>
              将合并开发版中的作者、帖子、项目关联、媒体、图片理解和已完成报告；不会删除线上数据，也不会带入活跃任务。
            </Typography.Paragraph>
            <Descriptions column={1} size="small" items={[
              { key: 'authors', label: '作者', children: formatNumber(counts.authors ?? 0) },
              { key: 'posts', label: '帖子', children: formatNumber(counts.posts ?? 0) },
              { key: 'projects', label: '项目', children: formatNumber(counts.projects ?? 0) },
            ]} />
          </Modal>
        </>
      )}
    </Card>
  );
}

export default function SettingsPage() {
  const [activeSection, setActiveSection] = useState<SettingsSectionKey>('defaults');
  const settings = useQuery({
    queryKey: queryKeys.settings,
    queryFn: ({ signal }) => apiService.settings(signal),
  });
  const stats = useQuery({
    queryKey: queryKeys.stats,
    queryFn: ({ signal }) => apiService.stats(signal),
  });

  useEffect(() => {
    if (!settings.data) return;

    let animationFrame = 0;
    const updateActiveSection = () => {
      window.cancelAnimationFrame(animationFrame);
      animationFrame = window.requestAnimationFrame(() => {
        const next = activeSettingsSection(
          SETTINGS_SECTIONS.map((section) => ({
            key: section.key,
            top: document.getElementById(`settings-${section.key}`)?.getBoundingClientRect().top
              ?? Number.POSITIVE_INFINITY,
          })),
          128,
          window.scrollY + window.innerHeight
            >= Math.max(document.documentElement.scrollHeight, document.body.scrollHeight) - 4,
        );
        if (next) setActiveSection((current) => (current === next ? current : next));
      });
    };

    updateActiveSection();
    window.addEventListener('scroll', updateActiveSection, { passive: true });
    window.addEventListener('resize', updateActiveSection);
    return () => {
      window.cancelAnimationFrame(animationFrame);
      window.removeEventListener('scroll', updateActiveSection);
      window.removeEventListener('resize', updateActiveSection);
    };
  }, [settings.data]);

  const goToSection = (key: SettingsSectionKey) => {
    setActiveSection(key);
    document.getElementById(`settings-${key}`)?.scrollIntoView({
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
      block: 'start',
    });
  };

  if (settings.isPending) {
    return (
      <PageContainer title="后台配置">
        <Card>
          <QueryLoading rows={8} />
        </Card>
      </PageContainer>
    );
  }

  if (settings.isError || !settings.data) {
    return (
      <PageContainer title="后台配置">
        <QueryError error={settings.error} retry={() => void settings.refetch()} />
      </PageContainer>
    );
  }

  return (
    <PageContainer
      title="后台配置"
      content="配置统一作用于本地服务；每个分区独立保存，项目内任务仍可在启动前单独调整。"
      extra={[
        <Button
          key="refresh"
          icon={<ReloadOutlined />}
          loading={settings.isFetching || stats.isFetching}
          onClick={() => {
            void settings.refetch();
            void stats.refetch();
          }}
        >
          重新读取
        </Button>,
      ]}
    >
      <div className="settings-page-layout">
        <nav className="settings-page-nav" aria-label="后台配置分区">
          <Menu
            mode="inline"
            selectedKeys={[activeSection]}
            items={SETTINGS_SECTION_GROUPS.map((group) => ({
              type: 'group' as const,
              key: group.key,
              label: group.label,
              children: group.sections.map((section) => ({
                key: section.key,
                label: section.label,
                icon: sectionIcons[section.key],
              })),
            }))}
            onClick={({ key }) => goToSection(key as SettingsSectionKey)}
          />
        </nav>
        <div className="settings-page-stack">
          {SETTINGS_SECTION_GROUPS.map((group) => {
            if (group.key === 'research') {
              return (
                <SettingsGroup
                  key={group.key}
                  groupKey={group.key}
                  title={group.label}
                  description={group.description}
                >
                  <DefaultsSection settings={settings.data} />
                  <SourceSection settings={settings.data} />
                  <RefreshSection settings={settings.data} />
                </SettingsGroup>
              );
            }
            if (group.key === 'processing') {
              return (
                <SettingsGroup
                  key={group.key}
                  groupKey={group.key}
                  title={group.label}
                  description={group.description}
                >
                  <VisionSection settings={settings.data} />
                  <ReportPromptsSection settings={settings.data} />
                  <CapabilityRoutingSection settings={settings.data} />
                </SettingsGroup>
              );
            }
            if (group.key === 'identity') {
              return (
                <SettingsGroup
                  key={group.key}
                  groupKey={group.key}
                  title={group.label}
                  description={group.description}
                >
                  <MyAuthorSection settings={settings.data} />
                </SettingsGroup>
              );
            }
            return (
              <SettingsGroup
                key={group.key}
                groupKey={group.key}
                title={group.label}
                description={group.description}
              >
                <ServiceSection settings={settings.data} />
                <StorageSection settings={settings.data} stats={stats} />
                <DataReleaseSection settings={settings.data} />
              </SettingsGroup>
            );
          })}
        </div>
      </div>
    </PageContainer>
  );
}
