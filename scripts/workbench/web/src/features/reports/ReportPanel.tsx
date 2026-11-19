import {
  DownloadOutlined,
  FileTextOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { XMarkdown } from '@ant-design/x-markdown';
import '@ant-design/x-markdown/themes/light.css';
import { ProCard } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import {
  Button,
  Collapse,
  Descriptions,
  Empty,
  Flex,
  Select,
  Space,
  Tabs,
  Tag,
  Typography,
} from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { QueryError, QueryLoading } from '@/components/QueryState';
import { apiService } from '@/services/api';
import { queryKeys } from '@/services/queryKeys';
import type { Report, ReportStatus, TaskReceipt } from '@/types';
import { formatDate, formatNumber } from '@/utils/format';
import DataSummaryView, { isDataSummaryPayload } from './DataSummaryView';
import ReportPresentationModal from './ReportPresentationModal';
import { reportDisplayVersion } from './presentation';
import { reportContextSummary } from './reportContext';

type ReportKind = 'summary' | 'llm';

function kindOf(report: Report): ReportKind {
  return report.generator_type === 'llm' ? 'llm' : 'summary';
}

const summaryOperationLabels: Record<string, string> = {
  research: '采集任务',
  project_author_update: '作者更新',
  author_update: '作者更新',
  post_detail_update: '帖子详情更新',
  ocr: 'OCR',
  vision: '大模型识图',
};

function summarySourceLabel(report: Report): string {
  if (kindOf(report) !== 'summary') return '';
  const trigger = String(report.generation_config_json.trigger || '');
  if (trigger !== 'automatic') return '手动';
  const operation = String(report.generation_config_json.operation || '');
  return operation ? `自动 · ${summaryOperationLabels[operation] || operation}` : '自动';
}

function VersionSelect({
  kind,
  reports,
  value,
  onChange,
}: {
  kind: ReportKind;
  reports: Report[];
  value?: number;
  onChange: (id: number) => void;
}) {
  if (!reports.length) return null;
  const generatingReport = reports.find((item) => item.status === 'generating');
  return (
    <Space>
      <Typography.Text type="secondary">历史版本</Typography.Text>
      <Select
        value={value}
        onChange={onChange}
        style={{ minWidth: 220 }}
        placeholder={
          generatingReport
            ? `v${reportDisplayVersion(generatingReport)} · 生成中`
            : undefined
        }
        aria-label={`${kind === 'llm' ? '大模型报告' : '数据摘要'}历史版本`}
        options={reports.map((item) => ({
          value: item.id,
          label:
            item.status === 'generating'
              ? `v${reportDisplayVersion(item)} · 生成中`
              : `v${reportDisplayVersion(item)}${kind === 'summary' ? ` · ${summarySourceLabel(item)}` : ''} · ${formatDate(item.generated_at)}`,
          disabled: item.status === 'generating',
        }))}
      />
    </Space>
  );
}

function LegacySummary({ report }: { report: Report }) {
  return (
    <ProCard variant="outlined">
      <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
        <Typography.Text type="secondary">
          这是旧版数据摘要，未记录的新统计项不会用当前数据补写。重新生成后可查看完整描述性统计。
        </Typography.Text>
        <XMarkdown
          className="x-markdown-light report-markdown"
          content={report.content_markdown || '这份旧版摘要没有正文。'}
          openLinksInNewTab
          escapeRawHtml
        />
      </Space>
    </ProCard>
  );
}

function SummaryPanel({
  reports,
  onGenerate,
  generating,
  onOpenPost,
}: {
  reports: Report[];
  onGenerate: () => void;
  generating: boolean;
  onOpenPost?: (id: number) => void;
}) {
  const completed = reports.filter((item) => item.status !== 'generating');
  const [reportId, setReportId] = useState<number>();
  useEffect(() => {
    setReportId((current) =>
      completed.some((item) => item.id === current) ? current : completed[0]?.id,
    );
  }, [completed]);
  const report = completed.find((item) => item.id === reportId) || completed[0];
  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
      <Flex justify="space-between" gap="middle" wrap align="center">
        <VersionSelect
          kind="summary"
          reports={completed}
          value={report?.id}
          onChange={setReportId}
        />
        <Button icon={<ReloadOutlined />} loading={generating} onClick={onGenerate}>
          {report ? '刷新数据摘要' : '生成数据摘要'}
        </Button>
      </Flex>
      {!report ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有数据摘要">
          <Button type="primary" onClick={onGenerate} loading={generating}>
            生成第一份数据摘要
          </Button>
        </Empty>
      ) : (
        <>
          <Flex justify="space-between" gap="middle" wrap align="center">
            <div>
              <Typography.Title level={3} style={{ margin: 0 }}>
                {report.title}
              </Typography.Title>
              <Typography.Text type="secondary">
                数据快照：{formatDate(report.generated_at)}
              </Typography.Text>
            </div>
            <Space size="small">
              <Tag>{summarySourceLabel(report)}</Tag>
              <Tag icon={<FileTextOutlined />}>版本 {reportDisplayVersion(report)}</Tag>
            </Space>
          </Flex>
          {isDataSummaryPayload(report.summary_json) ? (
            <DataSummaryView value={report.summary_json} onOpenPost={onOpenPost} />
          ) : (
            <LegacySummary report={report} />
          )}
        </>
      )}
    </Space>
  );
}

const presentationPageModeLabels = {
  concise: '精简',
  standard: '标准',
  complete: '完整',
};

function PresentationHistory({
  target,
  report,
}: {
  target: { type: 'project' | 'author'; id: number };
  report: Report;
}) {
  const query = useQuery({
    queryKey: queryKeys.reportPresentations(target.type, target.id, report.id),
    queryFn: () => apiService.reportPresentations(target, report.id),
    refetchInterval: (state) =>
      state.state.data?.some((item) => item.status === 'generating') ? 1500 : false,
  });
  if (query.isError) return <QueryError error={query.error} retry={() => query.refetch()} />;
  if (query.isPending) return null;
  if (!query.data.length) return null;
  return (
    <ProCard title="HTML 演示稿" variant="outlined">
      <Space orientation="vertical" size="small" style={{ width: '100%' }}>
        {query.data.map((item) => (
          <Flex key={item.id} justify="space-between" align="center" gap="middle" wrap>
            <Space wrap>
              <Typography.Text strong>{item.title}</Typography.Text>
              <Tag>v{item.version}</Tag>
              <Tag>
                {presentationPageModeLabels[item.page_mode]} · {item.slide_count || '—'} 页
              </Tag>
              <Typography.Text type="secondary">
                {item.status === 'generating' ? '生成中' : formatDate(item.generated_at)}
              </Typography.Text>
            </Space>
            {item.status === 'completed' ? (
              <Space>
                <Button
                  icon={<PlayCircleOutlined />}
                  onClick={() =>
                    window.open(
                      apiService.reportPresentationHtmlUrl(item.id),
                      '_blank',
                      'noopener,noreferrer',
                    )
                  }
                >
                  预览
                </Button>
                <Button
                  icon={<DownloadOutlined />}
                  onClick={() =>
                    window.open(
                      apiService.reportPresentationHtmlUrl(item.id, true),
                      '_blank',
                      'noopener,noreferrer',
                    )
                  }
                >
                  下载 HTML
                </Button>
              </Space>
            ) : null}
          </Flex>
        ))}
      </Space>
    </ProCard>
  );
}

function LlmPanel({
  reports,
  status,
  statusError,
  statusLoading,
  onRetryStatus,
  onGenerate,
  target,
  onPresentationCreated,
}: {
  reports: Report[];
  status?: ReportStatus;
  statusError?: unknown;
  statusLoading: boolean;
  onRetryStatus?: () => void;
  onGenerate: () => void;
  target?: { type: 'project' | 'author'; id: number };
  onPresentationCreated?: (task: TaskReceipt) => void | Promise<void>;
}) {
  const completed = reports.filter((item) => item.status !== 'generating');
  const generatingReport = reports.find((item) => item.status === 'generating');
  const [reportId, setReportId] = useState<number>();
  const [presentationOpen, setPresentationOpen] = useState(false);
  useEffect(() => {
    setReportId((current) =>
      completed.some((item) => item.id === current) ? current : completed[0]?.id,
    );
  }, [completed]);
  const report = completed.find((item) => item.id === reportId) || completed[0];
  const generateUnavailable =
    statusLoading || Boolean(statusError) || !status?.provider_available || Boolean(generatingReport);
  return (
    <>
      <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
      {statusError ? <QueryError error={statusError} retry={onRetryStatus} /> : null}
      {statusLoading && !status ? <QueryLoading rows={2} /> : null}
      <Flex justify="space-between" gap="middle" wrap align="center">
        <VersionSelect
          kind="llm"
          reports={reports}
          value={report?.id}
          onChange={setReportId}
        />
        <Button
          type="primary"
          icon={report ? <ReloadOutlined /> : <PlusOutlined />}
          onClick={onGenerate}
          disabled={generateUnavailable}
          title={
            statusError
              ? '报告能力状态加载失败，请先重试'
              : generatingReport
                ? '已有大模型报告正在生成'
                : !status?.provider_available
                  ? '大模型报告能力当前不可用'
                  : undefined
          }
        >
          {report ? '重新生成大模型报告' : '生成大模型报告'}
        </Button>
      </Flex>
      {!report ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={generatingReport ? '报告正在生成，完成后即可查看' : '还没有大模型报告'}
        />
      ) : (
        <>
          <ProCard variant="outlined">
            <Space orientation="vertical" size="large" style={{ width: '100%' }}>
              <Flex justify="space-between" align="center" gap="middle" wrap>
                <div>
                  <Typography.Title level={3} style={{ margin: 0 }}>
                    {report.title}
                  </Typography.Title>
                  <Typography.Text type="secondary">
                    {formatDate(report.generated_at)} · {report.model || report.generator_type}
                  </Typography.Text>
                </div>
                <Space wrap>
                  <Tag icon={<FileTextOutlined />}>版本 {reportDisplayVersion(report)}</Tag>
                  {target && onPresentationCreated ? (
                    <Button
                      icon={<PlayCircleOutlined />}
                      onClick={() => setPresentationOpen(true)}
                      disabled={Boolean(generatingReport)}
                    >
                      制作 HTML 演示稿
                    </Button>
                  ) : null}
                </Space>
              </Flex>
              {target ? <PresentationHistory target={target} report={report} /> : null}
              <XMarkdown
                className="x-markdown-light report-markdown"
                content={report.content_markdown || '这份报告没有正文。'}
                openLinksInNewTab
                escapeRawHtml
              />
            </Space>
          </ProCard>
          <Collapse
            size="small"
            items={[
              {
                key: 'evidence',
                label: '生成依据',
                children: (
                  <Descriptions
                    size="small"
                    column={{ xs: 1, sm: 2, lg: 3 }}
                    items={[
                      {
                        key: 'task',
                        label: '生成任务',
                        children: report.task_id ? <span className="mono">{report.task_id}</span> : '—',
                      },
                      { key: 'model', label: '模型', children: report.model || '—' },
                      { key: 'prompt', label: '提示词版本', children: report.prompt_version || '—' },
                      {
                        key: 'context',
                        label: '输入上下文',
                        children: reportContextSummary(report.generation_config_json),
                      },
                      {
                        key: 'posts',
                        label: '快照帖子',
                        children: formatNumber(report.evidence_post_count),
                      },
                      {
                        key: 'authors',
                        label: '快照作者',
                        children: formatNumber(report.evidence_author_count),
                      },
                      {
                        key: 'ocr',
                        label: 'OCR 帖子',
                        children: formatNumber(report.evidence_snapshot_json.ocr_post_count),
                      },
                      {
                        key: 'vision',
                        label: '识图帖子',
                        children: formatNumber(report.evidence_snapshot_json.vision_post_count),
                      },
                    ]}
                  />
                ),
              },
            ]}
          />
        </>
      )}
      </Space>
      {target && onPresentationCreated ? (
        <ReportPresentationModal
          target={target}
          report={report}
          open={presentationOpen}
          onClose={() => setPresentationOpen(false)}
          onCreated={onPresentationCreated}
        />
      ) : null}
    </>
  );
}

export default function ReportPanel({
  reports,
  status,
  statusError,
  statusLoading = false,
  onRetryStatus,
  onGenerate,
  onGenerateSummary,
  summaryGenerating = false,
  scopeLabel = '项目',
  onOpenPost,
  target,
  onPresentationCreated,
}: {
  reports: Report[];
  status?: ReportStatus;
  statusError?: unknown;
  statusLoading?: boolean;
  onRetryStatus?: () => void;
  onGenerate: () => void;
  onGenerateSummary: () => void;
  summaryGenerating?: boolean;
  scopeLabel?: '项目' | '作者';
  onOpenPost?: (id: number) => void;
  target?: { type: 'project' | 'author'; id: number };
  onPresentationCreated?: (task: TaskReceipt) => void | Promise<void>;
}) {
  const byKind = useMemo(
    () => ({
      summary: reports.filter((item) => kindOf(item) === 'summary'),
      llm: reports.filter((item) => kindOf(item) === 'llm'),
    }),
    [reports],
  );
  return (
    <ProCard title={`${scopeLabel}报告`} direction="column">
      <Tabs
        defaultActiveKey="summary"
        items={[
          {
            key: 'summary',
            label: '数据摘要',
            children: (
              <SummaryPanel
                reports={byKind.summary}
                onGenerate={onGenerateSummary}
                generating={summaryGenerating}
                onOpenPost={onOpenPost}
              />
            ),
          },
          {
            key: 'llm',
            label: '大模型报告',
            children: (
              <LlmPanel
                reports={byKind.llm}
                status={status}
                statusError={statusError}
                statusLoading={statusLoading}
                onRetryStatus={onRetryStatus}
                onGenerate={onGenerate}
                target={target}
                onPresentationCreated={onPresentationCreated}
              />
            ),
          },
        ]}
      />
    </ProCard>
  );
}
