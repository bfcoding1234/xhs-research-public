import { CheckCircleOutlined, DatabaseOutlined } from '@ant-design/icons';
import {
  Descriptions,
  Flex,
  Progress,
  Segmented,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { TableColumnsType } from 'antd';
import { useState } from 'react';
import type {
  DataSummaryAuthorRow,
  DataSummaryDistribution,
  DataSummaryNoteworthyPost,
  DataSummaryPayload,
  DataSummaryTopPost,
} from '@/types';
import { formatDate, formatNumber, formatPublishDate } from '@/utils/format';
import {
  DailyTrendChart,
  DistributionChart,
  PostTypeChart,
  RegionMapChart,
} from './DataSummaryCharts';

type PostMetric = 'total_interactions' | 'likes' | 'favorites' | 'comments';
type AuthorMetric = 'post_count' | 'total_interactions' | 'followers' | 'average_interactions';

function percent(value: number, total: number): number {
  return total > 0 ? Math.round((value / total) * 100) : 0;
}

function percentText(value: number | null | undefined): string {
  return value == null ? '—' : `${Math.round(value * 100)}%`;
}

function Section({
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

function CoverageRow({ label, value, total }: { label: string; value: number; total: number }) {
  const coverage = percent(value, total);
  const missing = Math.max(0, total - value);
  return (
    <div className="data-summary-coverage-row">
      <Flex justify="space-between" align="baseline" gap="small" wrap>
        <Typography.Text strong>{label}</Typography.Text>
        <Typography.Text type="secondary" className="data-summary-coverage-count">
          有效 {formatNumber(value)} / {formatNumber(total)} · 缺失 {formatNumber(missing)}
        </Typography.Text>
      </Flex>
      <Progress
        percent={coverage}
        size="small"
        showInfo={false}
        status={coverage === 100 ? 'success' : 'normal'}
      />
    </div>
  );
}

function ProcessCoverage({
  title,
  value,
  total,
  note,
}: {
  title: string;
  value: number;
  total: number;
  note: string;
}) {
  const coverage = percent(value, total);
  return (
    <div className="data-summary-process-card">
      <Flex justify="space-between" align="start" gap="small">
        <Typography.Text strong>{title}</Typography.Text>
        {coverage === 100 && total > 0 ? <CheckCircleOutlined className="data-summary-complete-icon" /> : null}
      </Flex>
      <Typography.Title level={4} className="data-summary-process-value">
        {formatNumber(value)} <Typography.Text type="secondary">/ {formatNumber(total)}</Typography.Text>
      </Typography.Title>
      <Progress percent={coverage} size="small" showInfo={false} />
      <Typography.Text type="secondary">{note}</Typography.Text>
    </div>
  );
}

function ScopedProcessCoverage({
  title,
  rows,
}: {
  title: string;
  rows: Array<{ label: string; value: number; total: number; coveredPosts: number }>;
}) {
  const complete = rows.every((row) => row.total > 0 && percent(row.value, row.total) === 100);
  return (
    <div className="data-summary-process-card">
      <Flex justify="space-between" align="start" gap="small">
        <Typography.Text strong>{title}</Typography.Text>
        {complete ? <CheckCircleOutlined className="data-summary-complete-icon" /> : null}
      </Flex>
      <div className="data-summary-process-scope-list">
        {rows.map((row) => (
          <div key={row.label} className="data-summary-process-scope-row">
            <Flex justify="space-between" align="baseline" gap="small">
              <Typography.Text>{row.label}</Typography.Text>
              <Typography.Text strong>
                {formatNumber(row.value)} <Typography.Text type="secondary">/ {formatNumber(row.total)}</Typography.Text>
              </Typography.Text>
            </Flex>
            <Progress percent={percent(row.value, row.total)} size="small" showInfo={false} />
            <Typography.Text type="secondary">覆盖 {formatNumber(row.coveredPosts)} 篇帖子</Typography.Text>
          </div>
        ))}
      </div>
    </div>
  );
}

function SummaryContext({ summary }: { summary: DataSummaryPayload }) {
  const postTotal = summary.post_completeness.total;
  const authorTotal = summary.author_field_coverage?.total ?? summary.author_completeness?.total ?? 1;
  return (
    <div className="data-summary-context-panel">
      <div className="data-summary-scale-grid">
        <div className="data-summary-scale-card">
          <DatabaseOutlined />
          <Statistic title="快照帖子" value={postTotal} />
        </div>
        <div className="data-summary-scale-card">
          <DatabaseOutlined />
          <Statistic title={summary.scope === 'project' ? '快照作者' : '当前作者'} value={authorTotal} />
        </div>
      </div>
      <Descriptions
        className="data-summary-freshness"
        size="small"
        column={{ xs: 1, sm: 2, lg: 3 }}
        items={[
          { key: 'snapshot', label: '数据快照', children: formatDate(summary.captured_at) },
          { key: 'detail', label: '最近帖子详情', children: formatDate(summary.freshness.last_detail_at) },
          { key: 'profile', label: '最近作者资料', children: formatDate(summary.freshness.last_profile_at) },
          { key: 'ocr', label: '最近 OCR', children: formatDate(summary.freshness.last_ocr_at) },
          { key: 'vision', label: '最近图片理解', children: formatDate(summary.freshness.last_vision_at) },
        ]}
      />
    </div>
  );
}

function PostCompleteness({ summary }: { summary: DataSummaryPayload }) {
  const total = summary.post_completeness.total;
  const media = summary.field_coverage?.media;
  const fields = summary.field_coverage?.posts;
  const incompleteFields = fields ? ([
    ['标题', fields.title],
    ['正文', fields.content],
    ['发布时间', fields.publish_date],
    ['帖子类型', fields.note_type],
    ['点赞数', fields.likes],
    ['收藏数', fields.favorites],
    ['评论数', fields.comments],
  ] as Array<[string, number]>).filter(([, value]) => value < fields.total) : [];
  return (
    <Section
      title="帖子数据完善度"
      description="仅展示存在缺失的字段；以快照帖子数为统一分母，数值 0 是有效值。"
    >
      {fields && incompleteFields.length ? (
        <div className="data-summary-panel data-summary-coverage-panel">
          <div className="data-summary-coverage-list">
            {incompleteFields.map(([label, value]) => (
              <CoverageRow key={label} label={label} value={value} total={fields.total} />
            ))}
          </div>
        </div>
      ) : null}
      <Typography.Title level={5} className="data-summary-subheading">处理覆盖</Typography.Title>
      <Typography.Paragraph type="secondary">
        这里只统计快照中已经保存的处理结果，刷新数据摘要不会调用 OCR、图片理解或任何外部 Provider。
      </Typography.Paragraph>
      <div className="data-summary-process-grid">
        <ProcessCoverage
          title="帖子详情"
          value={summary.post_completeness.detailed}
          total={total}
          note={`覆盖 ${percent(summary.post_completeness.detailed, total)}% 的帖子`}
        />
        {media?.cover && media.detail ? (
          <ScopedProcessCoverage
            title="OCR 图片"
            rows={[
              { label: '封面图', value: media.cover.ocr_completed_images, total: media.cover.local, coveredPosts: media.cover.ocr_covered_posts },
              { label: '详情图片', value: media.detail.ocr_completed_images, total: media.detail.local, coveredPosts: media.detail.ocr_covered_posts },
            ]}
          />
        ) : (
          <ProcessCoverage
            title="OCR 图片"
            value={media?.ocr_completed_images ?? 0}
            total={media?.local ?? 0}
            note={`覆盖 ${formatNumber(media?.ocr_covered_posts)} 篇帖子`}
          />
        )}
        {media?.cover && media.detail ? (
          <ScopedProcessCoverage
            title="大模型理解"
            rows={[
              { label: '封面图', value: media.cover.vision_analyzed_images, total: media.cover.local, coveredPosts: media.cover.vision_covered_posts },
              { label: '详情图片', value: media.detail.vision_analyzed_images, total: media.detail.local, coveredPosts: media.detail.vision_covered_posts },
            ]}
          />
        ) : (
          <ProcessCoverage
            title="图片理解结果"
            value={media?.vision_analyzed_images ?? 0}
            total={media?.local ?? 0}
            note={`已有结果覆盖 ${formatNumber(media?.vision_covered_posts)} 篇帖子`}
          />
        )}
      </div>
    </Section>
  );
}

function DistributionDetails({ distribution }: { distribution: DataSummaryDistribution }) {
  return (
    <Descriptions
      size="small"
      column={{ xs: 2, sm: 3 }}
      items={[
        { key: 'count', label: '有效样本', children: formatNumber(distribution.count) },
        { key: 'median', label: '中位数', children: formatNumber(distribution.median) },
        { key: 'average', label: '平均数', children: formatNumber(distribution.average) },
        { key: 'p75', label: 'P75', children: formatNumber(distribution.p75) },
        { key: 'p90', label: 'P90', children: formatNumber(distribution.p90) },
        { key: 'max', label: '最大值', children: formatNumber(distribution.max) },
      ]}
    />
  );
}

function InteractionDistribution({ summary }: { summary: DataSummaryPayload }) {
  const [metric, setMetric] = useState<PostMetric>('likes');
  const definitions: Record<Exclude<PostMetric, 'total_interactions'>, { label: string; value: DataSummaryDistribution }> = {
    likes: { label: '点赞', value: summary.interactions.likes },
    favorites: { label: '收藏', value: summary.interactions.favorites },
    comments: { label: '评论', value: summary.interactions.comments },
  };
  const activeMetric = metric === 'total_interactions' ? 'likes' : metric;
  const active = definitions[activeMetric];
  return (
    <div className="data-summary-panel data-summary-interaction-panel">
      <Flex justify="space-between" align="center" gap="middle" wrap>
        <Typography.Title level={5}>互动数据分布</Typography.Title>
        <Segmented
          size="small"
          value={activeMetric}
          options={Object.entries(definitions).map(([value, item]) => ({ value, label: item.label }))}
          onChange={(value) => setMetric(value as PostMetric)}
        />
      </Flex>
      <DistributionChart distribution={active.value} label={active.label} sampleTotal={summary.post_completeness.total} />
      <DistributionDetails distribution={active.value} />
    </div>
  );
}

function PostDistributions({ summary }: { summary: DataSummaryPayload }) {
  return (
    <Section
      title="帖子业务分布"
      description="趋势可切换发布帖子数、周期去重作者数和按发布时间归组的快照累计互动；数据跨度决定日、周或月粒度。"
    >
      <DailyTrendChart summary={summary} />
      <div className="data-summary-split-grid data-summary-description-grid data-summary-chart-grid">
        <div className="data-summary-panel">
          <Typography.Title level={5}>帖子类型</Typography.Title>
          <PostTypeChart summary={summary} />
        </div>
        <InteractionDistribution summary={summary} />
      </div>
    </Section>
  );
}

function postMetricValue(row: DataSummaryTopPost, metric: PostMetric): number | null | undefined {
  if (metric === 'total_interactions') return row.total_interactions;
  if (metric === 'likes') return row.likes_count;
  if (metric === 'favorites') return row.favorites_count;
  return row.comments_count;
}

function TopPosts({ summary, onOpenPost }: { summary: DataSummaryPayload; onOpenPost?: (id: number) => void }) {
  const [metric, setMetric] = useState<PostMetric>('total_interactions');
  const groups = summary.top_posts_by_metric ?? { total_interactions: summary.top_posts };
  const definitions: Array<{ value: PostMetric; label: string }> = [
    { value: 'total_interactions', label: '总互动' },
    { value: 'likes', label: '点赞' },
    { value: 'favorites', label: '收藏' },
    { value: 'comments', label: '评论' },
  ];
  const activeLabel = definitions.find((item) => item.value === metric)?.label ?? '总互动';
  const data = groups[metric] ?? [];
  const columns: TableColumnsType<DataSummaryTopPost> = [
    { title: '排名', key: 'rank', width: 68, render: (_, __, index) => index + 1 },
    {
      title: '帖子', dataIndex: 'title', key: 'title', width: 320,
      render: (value, row) => onOpenPost ? (
        <Typography.Link onClick={() => onOpenPost(row.id)}>{value || '无标题'}</Typography.Link>
      ) : value || '无标题',
    },
    ...(summary.scope === 'project'
      ? [{ title: '作者', dataIndex: 'author_name', key: 'author', width: 160, render: (value: string) => value || '未知作者' }]
      : []),
    { title: '发布时间', dataIndex: 'publish_date', key: 'publish', width: 140, render: formatPublishDate },
    {
      title: activeLabel,
      key: 'metric',
      width: 120,
      align: 'right',
      render: (_, row) => <Typography.Text strong>{formatNumber(postMetricValue(row, metric))}</Typography.Text>,
    },
  ];
  const eligible = metric === 'total_interactions'
    ? summary.interactions.complete_post_count
    : summary.field_coverage?.posts[metric] ?? 0;
  return (
    <Section
      title="Top 帖子"
      description={metric === 'total_interactions'
        ? `严格使用点赞、收藏、评论全部完整的 ${formatNumber(eligible)} 篇帖子；任一字段缺失即不参与排名。`
        : `仅使用${activeLabel}字段有效的 ${formatNumber(eligible)} 篇帖子；并列时按完整总互动和帖子 ID 确定顺序。`}
    >
      <Segmented
        className="data-summary-metric-switch"
        value={metric}
        options={definitions}
        onChange={(value) => setMetric(value as PostMetric)}
      />
      <Table<DataSummaryTopPost>
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={data}
        pagination={false}
        scroll={{ x: 820 }}
      />
    </Section>
  );
}

function NoteworthyPosts({
  summary,
  onOpenPost,
}: {
  summary: DataSummaryPayload;
  onOpenPost?: (id: number) => void;
}) {
  const noteworthy = summary.noteworthy_posts;
  if (summary.scope !== 'project' || !noteworthy) return null;
  const { criteria, items } = noteworthy;
  const columns: TableColumnsType<DataSummaryNoteworthyPost> = [
    {
      title: '关注分',
      dataIndex: 'attention_score',
      key: 'attention',
      width: 92,
      align: 'right',
      render: (value) => <Typography.Text strong>{formatNumber(value)}</Typography.Text>,
    },
    {
      title: '帖子',
      dataIndex: 'title',
      key: 'title',
      width: 300,
      render: (value, row) => onOpenPost ? (
        <Typography.Link onClick={() => onOpenPost(row.id)}>{value || '无标题'}</Typography.Link>
      ) : value || '无标题',
    },
    {
      title: '总互动',
      dataIndex: 'total_interactions',
      key: 'interactions',
      width: 104,
      align: 'right',
      render: formatNumber,
    },
    {
      title: '作者',
      key: 'author',
      width: 160,
      render: (_, row) => row.author.name || '未知作者',
    },
    {
      title: '作者粉丝',
      key: 'followers',
      width: 112,
      align: 'right',
      render: (_, row) => formatNumber(row.author.followers_count),
    },
    {
      title: '平滑每千粉互动',
      dataIndex: 'smoothed_interactions_per_1000_followers',
      key: 'smoothed',
      width: 150,
      align: 'right',
      render: formatNumber,
    },
    {
      title: '项目帖子',
      key: 'projectPosts',
      width: 104,
      align: 'right',
      render: (_, row) => formatNumber(row.author.project_post_count),
    },
    {
      title: '作者获赞收藏',
      key: 'authorLikes',
      width: 132,
      align: 'right',
      render: (_, row) => formatNumber(row.author.likes_collections_count),
    },
  ];
  return (
    <Section
      title="值得关注的帖子"
      description={`关注分以互动/粉丝为主体，并平滑小粉丝和低互动样本；本次 K=${formatNumber(criteria.follower_smoothing)}、T=${formatNumber(criteria.interaction_smoothing)}，有效帖子 ${formatNumber(criteria.eligible_post_count)} 篇、作者 ${formatNumber(criteria.eligible_author_count)} 位。`}
    >
      <Table<DataSummaryNoteworthyPost>
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={items}
        pagination={false}
        locale={{ emptyText: '暂无互动与作者粉丝数据均完整的帖子' }}
        scroll={{ x: 1150 }}
      />
    </Section>
  );
}

function AuthorCompleteness({ summary }: { summary: DataSummaryPayload }) {
  const coverage = summary.author_field_coverage;
  if (!coverage) return null;
  const fields = [
    ['昵称', coverage.display_name],
    ['小红书号', coverage.xhs_id],
    ['简介', coverage.bio],
    ['地区', coverage.location],
    ['头像', coverage.avatar],
    ['粉丝数', coverage.followers],
    ['关注数', coverage.following],
    ['获赞与收藏数', coverage.likes_collections],
    ['发布帖子总数', coverage.published_posts],
    ['作者资料已获取', coverage.profile_updated],
  ].filter((item): item is [string, number] => (
    typeof item[1] === 'number' && item[1] < coverage.total
  ));
  if (!fields.length) return null;
  return (
    <Section title="作者数据完善度" description="仅展示存在缺失的字段；以快照作者数为统一分母。">
      <div className="data-summary-panel data-summary-coverage-panel">
        <div className="data-summary-coverage-list">
          {fields.map(([label, value]) => (
            <CoverageRow key={label} label={label} value={value} total={coverage.total} />
          ))}
        </div>
      </div>
    </Section>
  );
}

function AuthorDistributions({ summary }: { summary: DataSummaryPayload }) {
  const stats = summary.author_statistics;
  const [metric, setMetric] = useState('followers');
  if (!stats) return null;
  const definitions = [
    { value: 'followers', label: '粉丝数', distribution: stats.followers },
    { value: 'following', label: '关注数', distribution: stats.following },
    { value: 'likes_collections', label: '获赞与收藏', distribution: stats.likes_collections },
    { value: 'published_posts', label: '发布帖子数', distribution: stats.published_posts },
    { value: 'post_count', label: '项目帖子数', distribution: stats.post_count },
    { value: 'total_interactions', label: '项目总互动', distribution: stats.total_interactions },
  ].filter((item): item is { value: string; label: string; distribution: DataSummaryDistribution } => Boolean(item.distribution));
  const active = definitions.find((item) => item.value === metric) ?? definitions[0];
  if (!active) return null;
  return (
    <Section title="作者业务分布" description="从作者体量和项目贡献两个角度观察结构；缺失值不按 0 计入。">
      <div className="data-summary-split-grid">
        <div className="data-summary-panel">
          <Segmented
            className="data-summary-metric-switch"
            size="small"
            value={active.value}
            options={definitions.map(({ value, label }) => ({ value, label }))}
            onChange={(value) => setMetric(String(value))}
          />
          <DistributionChart distribution={active.distribution} label={active.label} sampleTotal={summary.author_field_coverage?.total} />
          <DistributionDetails distribution={active.distribution} />
        </div>
        <div className="data-summary-panel">
          <Typography.Title level={5}>地区分布</Typography.Title>
          <RegionMapChart data={stats.locations ?? []} />
        </div>
      </div>
    </Section>
  );
}

function authorMetricValue(row: DataSummaryAuthorRow, metric: AuthorMetric): number | null | undefined {
  if (metric === 'post_count') return row.post_count;
  if (metric === 'total_interactions') return row.total_interactions;
  if (metric === 'followers') return row.followers_count;
  return row.average_interactions;
}

function TopAuthors({ summary }: { summary: DataSummaryPayload }) {
  const stats = summary.author_statistics;
  const [metric, setMetric] = useState<AuthorMetric>('post_count');
  if (!stats) return null;
  const groups = stats.top_authors_by_metric;
  const definitions: Array<{ value: AuthorMetric; label: string }> = [
    { value: 'post_count', label: '项目帖子数' },
    { value: 'total_interactions', label: '总互动' },
    { value: 'followers', label: '粉丝数' },
    ...(groups.average_interactions ? [{ value: 'average_interactions' as const, label: '篇均互动' }] : []),
  ];
  const activeLabel = definitions.find((item) => item.value === metric)?.label ?? '项目帖子数';
  const data = groups[metric] ?? [];
  const columns: TableColumnsType<DataSummaryAuthorRow> = [
    { title: '排名', key: 'rank', width: 68, render: (_, __, index) => index + 1 },
    { title: '作者', dataIndex: 'name', key: 'name', width: 240 },
    { title: '项目帖子', dataIndex: 'post_count', key: 'posts', width: 110, align: 'right', render: formatNumber },
    {
      title: activeLabel,
      key: 'metric',
      width: 130,
      align: 'right',
      render: (_, row) => <Typography.Text strong>{formatNumber(authorMetricValue(row, metric))}</Typography.Text>,
    },
    {
      title: '资料状态', dataIndex: 'profile_updated', key: 'profile', width: 110,
      render: (value) => <Tag color={value ? 'success' : 'default'}>{value ? '已获取' : '未获取'}</Tag>,
    },
  ];
  return (
    <Section
      title="Top 作者"
      description={metric === 'average_interactions'
        ? '篇均互动榜只纳入至少有 3 篇互动字段完整帖子的作者。'
        : `Top 10 作者贡献 ${metric === 'post_count' ? percentText(stats.top_10_post_share) : percentText(stats.top_10_interaction_share)} 的对应项目数据。`}
    >
      <Segmented
        className="data-summary-metric-switch"
        value={metric}
        options={definitions}
        onChange={(value) => setMetric(value as AuthorMetric)}
      />
      <Table<DataSummaryAuthorRow>
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={data}
        pagination={false}
        scroll={{ x: 680 }}
      />
    </Section>
  );
}

function SingleAuthorProfile({ summary }: { summary: DataSummaryPayload }) {
  const profile = summary.author_profile;
  if (!profile) return <AuthorCompleteness summary={summary} />;
  return (
    <>
      <AuthorCompleteness summary={summary} />
      <Section title="作者资料" description="单作者范围仅展示当前资料，不生成无统计意义的作者分布或 Top 作者。">
        <Descriptions
          bordered
          size="small"
          column={{ xs: 1, sm: 2, lg: 3 }}
          items={[
            { key: 'name', label: '昵称', children: profile.display_name || '—' },
            { key: 'xhs', label: '小红书号', children: profile.xhs_id || '—' },
            { key: 'location', label: '地区', children: profile.location || '—' },
            { key: 'followers', label: '粉丝数', children: formatNumber(profile.followers_count) },
            { key: 'following', label: '关注数', children: formatNumber(profile.following_count) },
            { key: 'likes', label: '获赞与收藏', children: formatNumber(profile.likes_collections_count) },
            { key: 'posts', label: '发布帖子总数', children: formatNumber(profile.published_posts) },
            { key: 'avatar', label: '头像', children: profile.has_avatar ? '已记录' : '未记录' },
            { key: 'updated', label: '资料更新时间', children: formatDate(profile.last_profile_at) },
            { key: 'bio', label: '简介', children: profile.bio || '—', span: 'filled' },
          ]}
        />
      </Section>
    </>
  );
}

export default function DataSummaryV2View({
  summary,
  onOpenPost,
}: {
  summary: DataSummaryPayload;
  onOpenPost?: (id: number) => void;
}) {
  const [module, setModule] = useState<'posts' | 'authors'>('posts');
  return (
    <div className="data-summary-layout">
      <SummaryContext summary={summary} />
      <Segmented
        className="data-summary-module-switch"
        size="large"
        block
        value={module}
        options={[
          { value: 'posts', label: `帖子 · ${formatNumber(summary.post_completeness.total)}` },
          {
            value: 'authors',
            label: summary.scope === 'project'
              ? `作者 · ${formatNumber(summary.author_field_coverage?.total ?? 0)}`
              : '作者资料',
          },
        ]}
        onChange={(value) => setModule(value as 'posts' | 'authors')}
      />
      {module === 'posts' ? (
        <>
          <PostCompleteness summary={summary} />
          <PostDistributions summary={summary} />
          <NoteworthyPosts summary={summary} onOpenPost={onOpenPost} />
          <TopPosts summary={summary} onOpenPost={onOpenPost} />
        </>
      ) : summary.scope === 'project' ? (
        <>
          <AuthorCompleteness summary={summary} />
          <AuthorDistributions summary={summary} />
          <TopAuthors summary={summary} />
        </>
      ) : (
        <SingleAuthorProfile summary={summary} />
      )}
    </div>
  );
}
