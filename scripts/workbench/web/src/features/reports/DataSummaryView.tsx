import { ProCard } from '@ant-design/pro-components';
import {
  Alert,
  Button,
  Descriptions,
  Flex,
  Progress,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { TableColumnsType } from 'antd';
import type {
  DataSummaryDistribution,
  DataSummaryPayload,
  DataSummaryTopPost,
  JsonObject,
} from '@/types';
import {
  formatDate,
  formatNumber,
  formatPublishDate,
  taskStatusLabels,
  taskTypeLabels,
} from '@/utils/format';
import DataSummaryV2View from './DataSummaryV2View';

function isDataSummaryPayload(value: JsonObject): value is DataSummaryPayload {
  return (
    [1, 2, 3, 4, 5, 6].includes(Number(value.schema_version)) &&
    (value.scope === 'project' || value.scope === 'author') &&
    Boolean(value.core) &&
    Boolean(value.post_completeness) &&
    Array.isArray(value.top_posts)
  );
}

function percentage(value: number, total: number): number {
  return total > 0 ? Math.round((value / total) * 100) : 0;
}

function percentText(value: number | null): string {
  return value === null ? '—' : `${Math.round(value * 100)}%`;
}

function yesNo(value: boolean): string {
  return value ? '已记录' : '未记录';
}

function SummarySection({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="data-summary-section">
      <header className="data-summary-section-heading">
        <Typography.Title level={4}>{title}</Typography.Title>
        {description ? <Typography.Text type="secondary">{description}</Typography.Text> : null}
      </header>
      {children}
    </section>
  );
}

function CoreStatistics({ summary }: { summary: DataSummaryPayload }) {
  const items =
    summary.scope === 'project'
      ? [
          ['关键词', summary.core.keyword_count],
          ['帖子', summary.core.post_count],
          ['作者', summary.core.author_count],
          ['有效任务', summary.core.task_count],
        ]
      : [
          ['已存帖子', summary.core.stored_post_count],
          ['作者发布总数', summary.core.published_post_count],
          ['关联项目', summary.core.project_count],
          ['报告版本', summary.core.report_count],
        ];
  return (
    <SummarySection title="核心规模">
      <div className="data-summary-core-grid">
        {items.map(([label, value]) => (
          <Statistic key={String(label)} title={label} value={formatNumber(value)} />
        ))}
      </div>
    </SummarySection>
  );
}

function CoverageRow({
  label,
  value,
  total,
}: {
  label: string;
  value: number;
  total: number;
}) {
  return (
    <div className="data-summary-coverage-row">
      <Flex justify="space-between" gap="middle">
        <Typography.Text>{label}</Typography.Text>
        <Typography.Text strong>
          {formatNumber(value)} / {formatNumber(total)}
        </Typography.Text>
      </Flex>
      <Progress
        percent={percentage(value, total)}
        size="small"
        format={(percent) => `${percent ?? 0}%`}
      />
    </div>
  );
}

function Completeness({ summary }: { summary: DataSummaryPayload }) {
  const posts = summary.post_completeness;
  const authors = summary.author_completeness;
  return (
    <SummarySection title="完善度" description="查看帖子和作者资料的处理覆盖情况。">
      <div className="data-summary-split-grid">
        <ProCard title="帖子完善度" variant="outlined">
          <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
            <CoverageRow label="有帖子详情" value={posts.detailed} total={posts.total} />
            <CoverageRow label="OCR 已完成" value={posts.ocr} total={posts.total} />
            <CoverageRow label="大模型识图已完成" value={posts.vision} total={posts.total} />
          </Space>
        </ProCard>
        {authors ? (
          <ProCard title="作者完善度" variant="outlined">
            <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
              <CoverageRow label="基础资料已更新" value={authors.profile_updated} total={authors.total} />
              <CoverageRow label="已有详细帖子" value={authors.with_detailed_posts} total={authors.total} />
              <CoverageRow label="已有 OCR 帖子" value={authors.with_ocr_posts} total={authors.total} />
              <CoverageRow label="已有识图帖子" value={authors.with_vision_posts} total={authors.total} />
            </Space>
          </ProCard>
        ) : (
          <ProCard title="作者资料" variant="outlined">
            <Descriptions
              size="small"
              column={1}
              items={[
                { key: 'profile', label: '基础资料', children: yesNo(Boolean(summary.author_profile?.profile_updated)) },
                { key: 'avatar', label: '头像', children: yesNo(Boolean(summary.author_profile?.has_avatar)) },
                { key: 'bio', label: '简介', children: yesNo(Boolean(summary.author_profile?.has_bio)) },
                { key: 'followers', label: '粉丝数据', children: yesNo(Boolean(summary.author_profile?.has_followers)) },
                { key: 'updated', label: '资料更新时间', children: formatDate(summary.author_profile?.last_profile_at) },
              ]}
            />
          </ProCard>
        )}
      </div>
    </SummarySection>
  );
}

function TopPosts({
  summary,
  onOpenPost,
}: {
  summary: DataSummaryPayload;
  onOpenPost?: (id: number) => void;
}) {
  const columns: TableColumnsType<DataSummaryTopPost> = [
    {
      title: '帖子',
      dataIndex: 'title',
      key: 'title',
      width: 300,
      fixed: 'left',
      render: (value, row) =>
        onOpenPost ? (
          <Button type="link" className="data-summary-post-link" onClick={() => onOpenPost(row.id)}>
            {value || '无标题'}
          </Button>
        ) : (
          value || '无标题'
        ),
    },
    ...(summary.scope === 'project'
      ? [{
          title: '作者',
          dataIndex: 'author_name',
          key: 'author',
          width: 150,
          render: (value: string) => value || '未知作者',
        }]
      : []),
    {
      title: '类型',
      dataIndex: 'note_type',
      key: 'type',
      width: 90,
      render: (value) => value === 'video' ? '视频' : '图文',
    },
    {
      title: '发布时间',
      dataIndex: 'publish_date',
      key: 'publish',
      width: 130,
      render: (value) => formatPublishDate(value),
    },
    {
      title: '点赞',
      dataIndex: 'likes_count',
      key: 'likes',
      width: 100,
      align: 'right',
      render: formatNumber,
    },
    {
      title: '收藏',
      dataIndex: 'favorites_count',
      key: 'favorites',
      width: 100,
      align: 'right',
      render: formatNumber,
    },
    {
      title: '评论',
      dataIndex: 'comments_count',
      key: 'comments',
      width: 100,
      align: 'right',
      render: formatNumber,
    },
    {
      title: '数据状态',
      key: 'status',
      width: 230,
      render: (_, row) => (
        <Space size={[4, 4]} wrap>
          <Tag color={row.has_detail ? 'success' : 'default'}>详情</Tag>
          <Tag color={row.has_ocr_result ? 'success' : 'default'}>OCR</Tag>
          <Tag color={row.has_vision_result ? 'success' : 'default'}>识图</Tag>
        </Space>
      ),
    },
  ];
  return (
    <SummarySection title="Top 帖子" description={`排序依据：${summary.top_posts_ranking}`}>
      <Table<DataSummaryTopPost>
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={summary.top_posts}
        pagination={false}
        scroll={{ x: 1200 }}
      />
    </SummarySection>
  );
}

function interactionRows(summary: DataSummaryPayload) {
  const rows: Array<{ key: string; label: string; value: DataSummaryDistribution }> = [
    { key: 'likes', label: '点赞', value: summary.interactions.likes },
    { key: 'favorites', label: '收藏', value: summary.interactions.favorites },
    { key: 'comments', label: '评论', value: summary.interactions.comments },
  ];
  return rows;
}

function ContentAndInteractions({ summary }: { summary: DataSummaryPayload }) {
  return (
    <SummarySection title="内容与互动" description="概览内容类型、媒体覆盖和互动量分布。">
      <div className="data-summary-split-grid">
        <div className="data-summary-panel">
          <Typography.Title level={5}>内容构成</Typography.Title>
          <Descriptions
            size="small"
            column={2}
            items={[
              { key: 'image', label: '图文帖子', children: formatNumber(summary.content.image_posts) },
              { key: 'video', label: '视频帖子', children: formatNumber(summary.content.video_posts) },
              { key: 'other', label: '其他类型', children: formatNumber(summary.content.other_posts) },
              { key: 'media', label: '媒体文件', children: formatNumber(summary.content.media_count) },
              {
                key: 'local',
                label: '已存本地媒体',
                children: formatNumber(summary.content.local_media_count),
              },
              {
                key: 'average',
                label: '平均每篇媒体数',
                children: formatNumber(summary.content.average_media_per_post),
              },
              {
                key: 'period',
                label: '发布时间范围',
                span: 2,
                children:
                  summary.content.publish_start || summary.content.publish_end
                    ? `${formatPublishDate(summary.content.publish_start)} ～ ${formatPublishDate(summary.content.publish_end)}`
                    : '—',
              },
              {
                key: 'months',
                label: '按月发布',
                span: 2,
                children:
                  summary.content.publish_months.length > 0
                    ? summary.content.publish_months
                        .map((item) => `${item.month}：${formatNumber(item.count)}`)
                        .join('；')
                    : '—',
              },
            ]}
          />
        </div>
        <div className="data-summary-panel">
          <Typography.Title level={5}>互动数据分布</Typography.Title>
          <Typography.Paragraph type="secondary">
            完整互动数据 {formatNumber(summary.interactions.complete_post_count)} /{' '}
            {formatNumber(summary.post_completeness.total)} 篇；Top 10 占总互动量{' '}
            {percentText(summary.interactions.top_10_share)}。
          </Typography.Paragraph>
          <Table
            rowKey="key"
            size="small"
            pagination={false}
            scroll={{ x: 440 }}
            dataSource={interactionRows(summary)}
            columns={[
              { title: '指标', dataIndex: 'label', key: 'label', width: 90 },
              {
                title: '中位数',
                key: 'median',
                width: 85,
                align: 'right',
                render: (_, row) => formatNumber(row.value.median),
              },
              {
                title: '平均数',
                key: 'average',
                width: 85,
                align: 'right',
                render: (_, row) => formatNumber(row.value.average),
              },
              {
                title: 'P75',
                key: 'p75',
                width: 80,
                align: 'right',
                render: (_, row) => formatNumber(row.value.p75),
              },
              {
                title: '最大值',
                key: 'max',
                width: 90,
                align: 'right',
                render: (_, row) => formatNumber(row.value.max),
              },
            ]}
          />
        </div>
      </div>
    </SummarySection>
  );
}

function TitleAndQuality({ summary }: { summary: DataSummaryPayload }) {
  const features = summary.title_features;
  const posts = summary.post_completeness;
  const missingTotal = Number(posts.missing_publish_date || 0)
    + Number(posts.missing_interactions || 0)
    + Number(posts.missing_title || 0)
    + Number(posts.missing_content || 0);
  return (
    <>
      <SummarySection title="标题表面特征">
        <Descriptions
          size="small"
          column={2}
          items={[
            { key: 'numeric', label: '含数字', children: formatNumber(features.numeric) },
            { key: 'question', label: '疑问型', children: formatNumber(features.question) },
            { key: 'actionable', label: '教程/清单等', children: formatNumber(features.actionable) },
            { key: 'missing', label: '无标题', children: formatNumber(features.missing) },
            { key: 'median', label: '标题长度中位数', children: formatNumber(features.length_median) },
            { key: 'max', label: '标题最大长度', children: formatNumber(features.length_max) },
          ]}
        />
      </SummarySection>
      <SummarySection title="数据缺口">
        <Alert
          showIcon
          type={missingTotal > 0 ? 'warning' : 'success'}
          title={missingTotal > 0 ? `发现 ${formatNumber(missingTotal)} 项数据缺口` : '关键数据完整'}
          description={(
            <Descriptions
              size="small"
              column={{ xs: 1, sm: 2, lg: 4 }}
              items={[
                { key: 'publish', label: '缺少发布时间', children: formatNumber(posts.missing_publish_date) },
                { key: 'interactions', label: '互动数据不完整', children: formatNumber(posts.missing_interactions) },
                { key: 'title', label: '缺少标题', children: formatNumber(posts.missing_title) },
                { key: 'content', label: '缺少正文', children: formatNumber(posts.missing_content) },
              ]}
            />
          )}
        />
      </SummarySection>
    </>
  );
}

function ProjectDetails({ summary }: { summary: DataSummaryPayload }) {
  if (summary.scope !== 'project') return null;
  return (
    <>
      {summary.top_authors?.length ? (
        <SummarySection title="Top 作者" description="按项目帖子数排序">
          <Table
            rowKey="id"
            size="small"
            pagination={false}
            scroll={{ x: 760 }}
            dataSource={summary.top_authors}
            columns={[
              { title: '作者', dataIndex: 'name', key: 'name', width: 210 },
              {
                title: '粉丝',
                dataIndex: 'followers_count',
                key: 'followers',
                width: 110,
                align: 'right',
                render: formatNumber,
              },
              {
                title: '项目帖子',
                dataIndex: 'post_count',
                key: 'posts',
                width: 110,
                align: 'right',
                render: formatNumber,
              },
              {
                title: '详细帖子',
                dataIndex: 'detailed_post_count',
                key: 'detail',
                width: 110,
                align: 'right',
                render: formatNumber,
              },
              {
                title: 'OCR 帖子',
                dataIndex: 'ocr_post_count',
                key: 'ocr',
                width: 110,
                align: 'right',
                render: formatNumber,
              },
              {
                title: '识图帖子',
                dataIndex: 'vision_post_count',
                key: 'vision',
                width: 110,
                align: 'right',
                render: formatNumber,
              },
            ]}
          />
        </SummarySection>
      ) : null}
      <SummarySection title="项目构成">
        <div className="data-summary-split-grid">
          <div className="data-summary-panel">
            <Typography.Title level={5}>关键词</Typography.Title>
            <Descriptions
              size="small"
              column={1}
              items={[
                { key: 'total', label: '关键词总数', children: formatNumber(summary.keywords?.total) },
                { key: 'manual', label: '手动添加', children: formatNumber(summary.keywords?.manual) },
                { key: 'ai', label: 'AI 候选转入', children: formatNumber(summary.keywords?.ai_generated) },
              ]}
            />
          </div>
          <div className="data-summary-panel">
            <Typography.Title level={5}>任务构成</Typography.Title>
            <Descriptions
              size="small"
              column={1}
              items={[
                ...Object.entries(summary.tasks?.by_type || {}).map(([key, value]) => ({
                  key: `type-${key}`,
                  label: taskTypeLabels[key as keyof typeof taskTypeLabels] || key,
                  children: formatNumber(value),
                })),
                ...Object.entries(summary.tasks?.by_status || {}).map(([key, value]) => ({
                  key: `status-${key}`,
                  label: taskStatusLabels[key as keyof typeof taskStatusLabels] || key,
                  children: formatNumber(value),
                })),
              ]}
            />
          </div>
        </div>
      </SummarySection>
    </>
  );
}

function Freshness({ summary }: { summary: DataSummaryPayload }) {
  return (
    <SummarySection title="数据新鲜度">
      <Descriptions
        size="small"
        column={{ xs: 1, sm: 2, lg: 3 }}
        items={[
          ...(summary.scope === 'project'
            ? [{ key: 'task', label: '最近任务完成', children: formatDate(summary.freshness.last_task_at) }]
            : []),
          { key: 'detail', label: '最近帖子详情', children: formatDate(summary.freshness.last_detail_at) },
          { key: 'profile', label: '最近作者资料', children: formatDate(summary.freshness.last_profile_at) },
          { key: 'ocr', label: '最近 OCR', children: formatDate(summary.freshness.last_ocr_at) },
          { key: 'vision', label: '最近大模型识图', children: formatDate(summary.freshness.last_vision_at) },
        ]}
      />
    </SummarySection>
  );
}

export default function DataSummaryView({
  value,
  onOpenPost,
}: {
  value: JsonObject;
  onOpenPost?: (id: number) => void;
}) {
  if (!isDataSummaryPayload(value)) return null;
  if (Number(value.schema_version) >= 2) {
    return <DataSummaryV2View summary={value} onOpenPost={onOpenPost} />;
  }
  return (
    <div className="data-summary-layout">
      <CoreStatistics summary={value} />
      <Completeness summary={value} />
      <TopPosts summary={value} onOpenPost={onOpenPost} />
      <ContentAndInteractions summary={value} />
      <TitleAndQuality summary={value} />
      <ProjectDetails summary={value} />
      <Freshness summary={value} />
    </div>
  );
}

export { isDataSummaryPayload };
