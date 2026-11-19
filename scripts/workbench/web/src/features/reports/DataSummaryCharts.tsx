import { Area, Column, Pie } from '@ant-design/plots';
import { Empty, Segmented, Tooltip, Typography } from 'antd';
import { useState } from 'react';
import type { DataSummaryDistribution, DataSummaryPayload } from '@/types';
import { formatNumber } from '@/utils/format';

const CHART_HEIGHT = 260;

function ChartFrame({
  ariaLabel,
  children,
}: {
  ariaLabel: string;
  children: React.ReactNode;
}) {
  return (
    <div className="data-summary-chart-frame" role="img" aria-label={ariaLabel}>
      {children}
    </div>
  );
}

type TrendMetric = 'post_count' | 'author_count' | 'likes' | 'favorites' | 'comments';
type TrendPoint = NonNullable<DataSummaryPayload['content']['publish_trend']>['points'][number];

const TREND_METRICS: Array<{ value: TrendMetric; label: string }> = [
  { value: 'post_count', label: '发布帖子数' },
  { value: 'author_count', label: '发布作者数' },
  { value: 'likes', label: '累计点赞' },
  { value: 'favorites', label: '累计收藏' },
  { value: 'comments', label: '累计评论' },
];

function trendMetricValue(point: TrendPoint, metric: TrendMetric): number | null | undefined {
  if (metric === 'post_count') return point.post_count ?? point.count;
  if (metric === 'author_count') return point.author_count;
  if (metric === 'likes') return point.likes;
  if (metric === 'favorites') return point.favorites;
  return point.comments;
}

function trendMetricValidCount(point: TrendPoint, metric: TrendMetric): number {
  if (metric === 'likes') return point.likes_valid_post_count ?? 0;
  if (metric === 'favorites') return point.favorites_valid_post_count ?? 0;
  if (metric === 'comments') return point.comments_valid_post_count ?? 0;
  return 0;
}

export function DailyTrendChart({ summary }: { summary: DataSummaryPayload }) {
  const [metric, setMetric] = useState<TrendMetric>('post_count');
  const trend = summary.content.publish_trend;
  const points: TrendPoint[] = trend?.points ?? (summary.content.publish_daily ?? []).map((item) => ({
    period: item.date,
    count: item.count,
    post_count: item.count,
  }));
  const metricOptions = TREND_METRICS.map((item) => {
    const available = item.value === 'post_count'
      || points.some((point) => Object.hasOwn(point, item.value));
    return {
      ...item,
      disabled: !available,
      tooltip: available ? undefined : '该历史摘要未保存此项按周期数据，请刷新数据摘要',
    };
  });
  const selectedMetric = metricOptions.find((item) => item.value === metric)?.disabled
    ? 'post_count'
    : metric;
  const usesLegacyTrend = points.length > 0
    && metricOptions.some((item) => item.value !== 'post_count' && item.disabled);
  const activeMetric = TREND_METRICS.find((item) => item.value === selectedMetric)
    ?? { value: 'post_count' as const, label: '发布帖子数' };
  const values = points.flatMap((point) => {
    const value = trendMetricValue(point, selectedMetric);
    return value == null ? [] : [{ period: point.period, value }];
  });
  const publishedPostTotal = points.reduce(
    (total, point) => total + (point.post_count ?? point.count ?? 0),
    0,
  );
  const validPostTotal = selectedMetric === 'likes' || selectedMetric === 'favorites' || selectedMetric === 'comments'
    ? points.reduce((total, point) => total + trendMetricValidCount(point, selectedMetric), 0)
    : null;
  const granularityLabel = { day: '每日', week: '每周', month: '每月' }[trend?.granularity ?? 'day'];
  return (
    <div className="data-summary-trend-panel">
      <Segmented
        className="data-summary-metric-switch data-summary-trend-switch"
        size="small"
        value={selectedMetric}
        options={metricOptions}
        onChange={(value) => setMetric(value as TrendMetric)}
      />
      {usesLegacyTrend ? (
        <Typography.Text className="data-summary-chart-caption" type="secondary">
          该历史摘要只保存了发布帖子数；点击页面右上角“刷新数据摘要”生成新版快照后，可查看发布作者数及互动趋势。
        </Typography.Text>
      ) : null}
      {values.length ? (
        <ChartFrame
          ariaLabel={`${granularityLabel}${activeMetric.label}趋势，共 ${values.length} 个有效周期，单周期最高 ${Math.max(...values.map((item) => item.value))}`}
        >
          <Area
            data={values}
            xField="period"
            yField="value"
            height={CHART_HEIGHT}
            shapeField="smooth"
            style={{ fillOpacity: 0.16, lineWidth: 3 }}
            axis={{
              x: { title: false, labelAutoRotate: false },
              y: { title: activeMetric.label, labelFormatter: formatNumber, grid: true },
            }}
            tooltip={{ title: 'period' }}
          />
          <Typography.Text className="data-summary-chart-caption" type="secondary">
            {validPostTotal == null
              ? selectedMetric === 'author_count'
                ? `已按数据跨度使用${granularityLabel.replace('每', '')}粒度；同一作者在每个周期内只计一次。`
                : `已按数据跨度使用${granularityLabel.replace('每', '')}粒度；缺少发布时间的帖子不计入趋势。`
              : `按帖子发布时间归组截至快照时的累计值；互动字段有效 ${formatNumber(validPostTotal)} / ${formatNumber(publishedPostTotal)} 篇。`}
          </Typography.Text>
        </ChartFrame>
      ) : (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={points.length ? `当前快照没有可用于${activeMetric.label}的有效数据` : '没有可用于趋势统计的发布时间'}
        />
      )}
    </div>
  );
}

export function DistributionChart({
  distribution,
  label,
  sampleTotal,
}: {
  distribution: DataSummaryDistribution;
  label: string;
  sampleTotal?: number;
}) {
  const buckets = distribution.buckets ?? [];
  if (!buckets.length) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={`没有可用于${label}分布的样本`} />;
  return (
    <ChartFrame ariaLabel={`${label}分布，有效样本 ${distribution.count}`}>
      <Column
        data={buckets}
        xField="label"
        yField="count"
        height={CHART_HEIGHT}
        style={{ radiusTopLeft: 6, radiusTopRight: 6 }}
        axis={{
          x: { title: false, labelAutoRotate: false },
          y: { title: '帖子数', labelFormatter: formatNumber, grid: true },
        }}
        tooltip={{ title: 'label' }}
      />
      <Typography.Text className="data-summary-chart-caption" type="secondary">
        有效样本 {formatNumber(distribution.count)} 个
        {sampleTotal == null ? '' : `，缺失 ${formatNumber(Math.max(0, sampleTotal - distribution.count))} 个`}；缺失值不按 0 计入。
      </Typography.Text>
    </ChartFrame>
  );
}

export function PostTypeChart({ summary }: { summary: DataSummaryPayload }) {
  const data = [
    { type: '图文', count: summary.content.image_posts },
    { type: '视频', count: summary.content.video_posts },
    { type: '其他/未知', count: summary.content.other_posts },
  ];
  const total = summary.post_completeness.total;
  return (
    <ChartFrame ariaLabel={`帖子类型构成，共 ${total} 篇帖子`}>
      <Pie
        data={data}
        angleField="count"
        colorField="type"
        innerRadius={0.62}
        height={CHART_HEIGHT}
        legend={{ position: 'bottom' }}
        tooltip={{ title: 'type' }}
        label={{
          text: (datum: { count: number }) => `${formatNumber(datum.count)} · ${total ? Math.round((datum.count / total) * 100) : 0}%`,
          position: 'outside',
        }}
      />
      <Typography.Text className="data-summary-chart-caption" type="secondary">
        总计 {formatNumber(total)} 篇；悬浮查看各类型占比。
      </Typography.Text>
    </ChartFrame>
  );
}

type RegionTile = {
  name: string;
  shortName: string;
  column: number;
  row: number;
  aliases?: string[];
};

const REGION_TILES: RegionTile[] = [
  { name: '新疆', shortName: '新疆', column: 1, row: 2, aliases: ['新疆维吾尔自治区'] },
  { name: '西藏', shortName: '西藏', column: 1, row: 5, aliases: ['西藏自治区'] },
  { name: '青海', shortName: '青海', column: 2, row: 4 },
  { name: '云南', shortName: '云南', column: 2, row: 7 },
  { name: '甘肃', shortName: '甘肃', column: 3, row: 3 },
  { name: '四川', shortName: '四川', column: 3, row: 5 },
  { name: '宁夏', shortName: '宁夏', column: 4, row: 3, aliases: ['宁夏回族自治区'] },
  { name: '重庆', shortName: '重庆', column: 4, row: 5 },
  { name: '贵州', shortName: '贵州', column: 4, row: 6 },
  { name: '广西', shortName: '广西', column: 4, row: 7, aliases: ['广西壮族自治区'] },
  { name: '海南', shortName: '海南', column: 4, row: 8 },
  { name: '内蒙古', shortName: '内蒙古', column: 5, row: 2, aliases: ['内蒙古自治区'] },
  { name: '陕西', shortName: '陕西', column: 5, row: 4 },
  { name: '湖北', shortName: '湖北', column: 5, row: 5 },
  { name: '湖南', shortName: '湖南', column: 5, row: 6 },
  { name: '广东', shortName: '广东', column: 5, row: 7 },
  { name: '澳门', shortName: '澳门', column: 5, row: 8, aliases: ['澳门特别行政区'] },
  { name: '山西', shortName: '山西', column: 6, row: 3 },
  { name: '河南', shortName: '河南', column: 6, row: 4 },
  { name: '江西', shortName: '江西', column: 6, row: 6 },
  { name: '香港', shortName: '香港', column: 6, row: 8, aliases: ['香港特别行政区'] },
  { name: '北京', shortName: '北京', column: 7, row: 3 },
  { name: '河北', shortName: '河北', column: 7, row: 4 },
  { name: '安徽', shortName: '安徽', column: 7, row: 5 },
  { name: '福建', shortName: '福建', column: 7, row: 7 },
  { name: '辽宁', shortName: '辽宁', column: 8, row: 3 },
  { name: '天津', shortName: '天津', column: 8, row: 4 },
  { name: '山东', shortName: '山东', column: 8, row: 5 },
  { name: '江苏', shortName: '江苏', column: 8, row: 6 },
  { name: '浙江', shortName: '浙江', column: 8, row: 7 },
  { name: '黑龙江', shortName: '黑龙江', column: 9, row: 1 },
  { name: '吉林', shortName: '吉林', column: 9, row: 2 },
  { name: '上海', shortName: '上海', column: 9, row: 6 },
  { name: '台湾', shortName: '台湾', column: 9, row: 8 },
];

function cleanRegionLabel(value: string): string {
  return value.trim().replace(/^IP\s*属地\s*[:：]?\s*/i, '').trim();
}

function matchRegion(value: string): RegionTile | undefined {
  const cleaned = cleanRegionLabel(value);
  return REGION_TILES.find((region) => {
    const aliases = [region.name, `${region.name}省`, `${region.name}市`, ...(region.aliases ?? [])];
    return aliases.some((alias) => cleaned === alias || cleaned.startsWith(alias));
  });
}

function regionLevel(count: number, maximum: number): number {
  if (!count || !maximum) return 0;
  return Math.max(1, Math.min(5, Math.ceil((count / maximum) * 5)));
}

export function RegionMapChart({ data }: { data: Array<{ label: string; count: number }> }) {
  const [activeRegion, setActiveRegion] = useState<string | null>(null);
  if (!data.length) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有可用于地区分布的样本" />;

  const regionCounts = new Map<string, number>();
  const unmatchedCounts = new Map<string, number>();
  let total = 0;
  for (const item of data) {
    const count = Math.max(0, item.count);
    total += count;
    const region = matchRegion(item.label);
    if (region) {
      regionCounts.set(region.name, (regionCounts.get(region.name) ?? 0) + count);
    } else {
      const label = cleanRegionLabel(item.label) || '未知';
      unmatchedCounts.set(label, (unmatchedCounts.get(label) ?? 0) + count);
    }
  }

  const maximum = Math.max(0, ...regionCounts.values());
  const rankedRegions = REGION_TILES
    .map((region) => ({ ...region, count: regionCounts.get(region.name) ?? 0 }))
    .sort((left, right) => right.count - left.count || left.name.localeCompare(right.name, 'zh-CN'));
  const selected = rankedRegions.find((region) => region.name === activeRegion && region.count > 0)
    ?? rankedRegions.find((region) => region.count > 0);
  const unmatched = [...unmatchedCounts.entries()]
    .map(([label, count]) => ({ label, count }))
    .sort((left, right) => right.count - left.count || left.label.localeCompare(right.label, 'zh-CN'));
  const mappedTotal = [...regionCounts.values()].reduce((sum, count) => sum + count, 0);
  const percentage = (count: number) => total ? `${((count / total) * 100).toFixed(1)}%` : '0%';

  return (
    <ChartFrame ariaLabel={`作者地区分布地图，有效样本 ${total} 位，省级地区 ${regionCounts.size} 个`}>
      <div className="data-summary-region-map-heading">
        <div className="data-summary-region-map-active" aria-live="polite">
          <Typography.Text strong>{selected?.name ?? '暂无省级地区数据'}</Typography.Text>
          <Typography.Text type="secondary">
            {selected ? `${formatNumber(selected.count)} 位作者 · ${percentage(selected.count)}` : '可识别的省级 IP 属地为 0'}
          </Typography.Text>
        </div>
        <div className="data-summary-region-map-legend" role="img" aria-label="颜色图例：由浅到深表示作者数量由少到多">
          <Typography.Text type="secondary">少</Typography.Text>
          {[1, 2, 3, 4, 5].map((level) => <span key={level} className={`data-summary-region-map-swatch data-summary-region-level-${level}`} />)}
          <Typography.Text type="secondary">多</Typography.Text>
        </div>
      </div>
      <div className="data-summary-region-map-scroll">
        <section className="data-summary-region-map-canvas" aria-label="中国省级块状地图">
          {REGION_TILES.map((region) => {
            const count = regionCounts.get(region.name) ?? 0;
            const detail = `${region.name}：${formatNumber(count)} 位作者，占地区有效样本 ${percentage(count)}`;
            return (
              <Tooltip key={region.name} title={detail} mouseEnterDelay={0.1}>
                <div
                  className={`data-summary-region-tile data-summary-region-level-${regionLevel(count, maximum)}`}
                  style={{ gridColumn: region.column, gridRow: region.row }}
                  tabIndex={count > 0 ? 0 : -1}
                  role="img"
                  aria-label={detail}
                  onMouseEnter={() => count > 0 && setActiveRegion(region.name)}
                  onFocus={() => count > 0 && setActiveRegion(region.name)}
                >
                  {region.shortName}
                </div>
              </Tooltip>
            );
          })}
        </section>
      </div>
      {unmatched.length ? (
        <div className="data-summary-region-unmatched">
          <Typography.Text type="secondary">未定位到省级地图：</Typography.Text>
          {unmatched.map((item) => (
            <span key={item.label}>{item.label} {formatNumber(item.count)} · {percentage(item.count)}</span>
          ))}
        </div>
      ) : null}
      <Typography.Text className="data-summary-chart-caption" type="secondary">
        基于作者 IP 属地，按省级块状地图呈现；共识别 {formatNumber(mappedTotal)} / {formatNumber(total)} 位作者，颜色越深表示作者越多。
      </Typography.Text>
    </ChartFrame>
  );
}
