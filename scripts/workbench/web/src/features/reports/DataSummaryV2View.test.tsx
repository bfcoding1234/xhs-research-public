import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { DataSummaryDistribution, DataSummaryPayload } from '@/types';
import DataSummaryV2View from './DataSummaryV2View';

vi.mock('@ant-design/plots', () => ({
  Area: () => <div data-testid="antv-area-chart" />,
  Bar: () => <div data-testid="antv-bar-chart" />,
  Column: () => <div data-testid="antv-column-chart" />,
  Pie: () => <div data-testid="antv-pie-chart" />,
}));

const distribution: DataSummaryDistribution = {
  count: 2,
  average: 5,
  median: 5,
  p75: 7.5,
  p90: 9,
  max: 10,
  buckets: [
    { label: '0', min: 0, max: 0, count: 1 },
    { label: '1–9', min: 1, max: 9, count: 0 },
    { label: '10–99', min: 10, max: 99, count: 1 },
    { label: '100–999', min: 100, max: 999, count: 0 },
    { label: '1千–9999', min: 1000, max: 9999, count: 0 },
    { label: '1万+', min: 10000, max: null, count: 0 },
  ],
};

const summary: DataSummaryPayload = {
  schema_version: 6,
  scope: 'project',
  captured_at: '2026-08-03T08:00:00Z',
  subject: { id: 1, name: '测试项目' },
  core: { post_count: 3, author_count: 2 },
  post_completeness: {
    total: 3,
    detailed: 2,
    ocr: 1,
    vision: 1,
    missing_publish_date: 1,
    missing_interactions: 1,
    missing_title: 0,
    missing_content: 1,
  },
  content: {
    image_posts: 2,
    video_posts: 1,
    other_posts: 0,
    posts_with_media: 2,
    posts_with_local_media: 2,
    media_count: 5,
    local_media_count: 4,
    average_media_per_post: 1.67,
    publish_months: [{ month: '2026-08', count: 2 }],
    publish_start: '2026-08-01',
    publish_end: '2026-08-03',
    publish_daily: [
      { date: '2026-08-01', count: 1, change: 1, change_rate: null },
      { date: '2026-08-02', count: 0, change: -1, change_rate: -1 },
      { date: '2026-08-03', count: 1, change: 1, change_rate: null },
    ],
    publish_trend: {
      granularity: 'day',
      points: [
        {
          period: '2026-08-01',
          count: 1,
          post_count: 1,
          author_count: 1,
          likes: 10,
          likes_valid_post_count: 1,
          favorites: 5,
          favorites_valid_post_count: 1,
          comments: 2,
          comments_valid_post_count: 1,
        },
        {
          period: '2026-08-03',
          count: 1,
          post_count: 1,
          author_count: 1,
          likes: 0,
          likes_valid_post_count: 1,
          favorites: null,
          favorites_valid_post_count: 0,
          comments: null,
          comments_valid_post_count: 0,
        },
      ],
    },
  },
  field_coverage: {
    posts: {
      total: 3,
      title: 3,
      content: 2,
      publish_date: 2,
      note_type: 3,
      likes: 3,
      favorites: 2,
      comments: 2,
    },
    media: {
      total: 5,
      local: 4,
      ocr_completed_images: 3,
      ocr_covered_posts: 1,
      vision_analyzed_images: 2,
      vision_covered_posts: 1,
      cover: {
        total: 1,
        local: 1,
        ocr_completed_images: 1,
        ocr_covered_posts: 1,
        vision_analyzed_images: 1,
        vision_covered_posts: 1,
      },
      detail: {
        total: 4,
        local: 3,
        ocr_completed_images: 2,
        ocr_covered_posts: 1,
        vision_analyzed_images: 1,
        vision_covered_posts: 1,
      },
    },
  },
  interactions: {
    complete_post_count: 2,
    total_interactions: 20,
    top_10_share: 1,
    likes: distribution,
    favorites: distribution,
    comments: distribution,
  },
  title_features: {
    with_title: 3,
    missing: 0,
    numeric: 0,
    question: 0,
    actionable: 0,
    length_average: 4,
    length_median: 4,
    length_max: 6,
  },
  top_posts: [],
  top_posts_by_metric: {
    total_interactions: [],
    likes: [],
    favorites: [],
    comments: [],
  },
  top_posts_ranking: '总互动数',
  noteworthy_posts: {
    criteria: {
      follower_smoothing: 100,
      interaction_smoothing: 10,
      eligible_post_count: 2,
      eligible_author_count: 2,
      candidate_count: 2,
    },
    items: [{
      id: 9,
      title: '值得关注的示例帖',
      author_id: 8,
      author_name: '小体量作者',
      note_type: 'image',
      publish_date: '2026-08-01',
      likes_count: 100,
      favorites_count: 20,
      comments_count: 5,
      total_interactions: 125,
      has_detail: true,
      has_ocr_result: true,
      has_vision_result: false,
      author: {
        id: 8,
        name: '小体量作者',
        followers_count: 320,
        project_post_count: 2,
        likes_collections_count: 900,
      },
      smoothed_interactions_per_1000_followers: 297.62,
      interaction_confidence: 0.9259,
      attention_metric: 275.57,
      attention_score: 96,
    }],
  },
  author_field_coverage: {
    total: 2,
    profile_updated: 1,
    display_name: 2,
    xhs_id: 1,
    followers: 1,
    following: 1,
    likes_collections: 1,
    published_posts: 1,
    bio: 1,
    location: 0,
    avatar: 2,
  },
  author_statistics: {
    post_count: distribution,
    followers: distribution,
    following: distribution,
    likes_collections: distribution,
    published_posts: distribution,
    total_interactions: distribution,
    average_interactions: distribution,
    locations: [{ label: '上海', count: 1 }],
    top_10_post_share: 1,
    top_10_interaction_share: 1,
    top_authors_by_metric: { post_count: [], total_interactions: [], followers: [], average_interactions: [] },
  },
  freshness: {
    last_task_at: '2026-08-03T08:00:00Z',
    last_detail_at: '2026-08-03T08:00:00Z',
    last_profile_at: '2026-08-03T08:00:00Z',
    last_ocr_at: '2026-08-03T08:00:00Z',
    last_vision_at: '2026-08-03T08:00:00Z',
  },
};

describe('DataSummaryV2View', () => {
  it('shows processing and per-field coverage without treating zero values as missing', () => {
    render(<DataSummaryV2View summary={summary} />);

    expect(screen.getByText('帖子数据完善度')).toBeInTheDocument();
    expect(screen.getByText('评论数')).toBeInTheDocument();
    expect(screen.getAllByText(/有效 2 \/ 3 · 缺失 1/).length).toBeGreaterThan(0);
    const postCompleteness = screen.getByText('帖子数据完善度').closest('section');
    if (!postCompleteness) throw new Error('帖子数据完善度区块不存在');
    expect(within(postCompleteness).queryByText('标题')).not.toBeInTheDocument();
    expect(within(postCompleteness).queryByText('帖子类型')).not.toBeInTheDocument();
    expect(within(postCompleteness).queryByText('点赞数')).not.toBeInTheDocument();
    const ocrCard = screen.getByText('OCR 图片').closest<HTMLElement>('.data-summary-process-card');
    if (!ocrCard) throw new Error('OCR 处理覆盖卡片不存在');
    expect(within(ocrCard).getByText('封面图')).toBeInTheDocument();
    expect(within(ocrCard).getByText('详情图片')).toBeInTheDocument();
    expect(ocrCard).toHaveTextContent('1 / 1');
    expect(ocrCard).toHaveTextContent('2 / 3');
    const visionCard = screen.getByText('大模型理解').closest<HTMLElement>('.data-summary-process-card');
    if (!visionCard) throw new Error('大模型理解处理覆盖卡片不存在');
    expect(within(visionCard).getByText('封面图')).toBeInTheDocument();
    expect(within(visionCard).getByText('详情图片')).toBeInTheDocument();

    fireEvent.click(screen.getByText('作者 · 2'));
    expect(screen.getByText('作者数据完善度')).toBeInTheDocument();
    const authorCompleteness = screen.getByText('作者数据完善度').closest('section');
    if (!authorCompleteness) throw new Error('作者数据完善度区块不存在');
    expect(within(authorCompleteness).queryByText('昵称')).not.toBeInTheDocument();
    expect(within(authorCompleteness).queryByText('头像')).not.toBeInTheDocument();
    expect(within(authorCompleteness).getByText('小红书号')).toBeInTheDocument();
  });

  it('renders daily trend, interaction distributions, top lists, and author statistics', () => {
    render(<DataSummaryV2View summary={summary} />);

    expect(screen.getByRole('img', { name: /每日发布帖子数趋势，共 2 个有效周期/ })).toBeInTheDocument();
    fireEvent.click(screen.getByText('发布作者数'));
    expect(screen.getByRole('img', { name: /每日发布作者数趋势，共 2 个有效周期/ })).toBeInTheDocument();
    fireEvent.click(screen.getByText('累计点赞'));
    expect(screen.getByRole('img', { name: /每日累计点赞趋势，共 2 个有效周期/ })).toBeInTheDocument();
    expect(screen.getByText(/互动字段有效 2 \/ 2 篇。/)).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /点赞分布，有效样本 2/ })).toBeInTheDocument();
    expect(screen.getByTestId('antv-area-chart')).toBeInTheDocument();
    expect(screen.getAllByTestId('antv-column-chart')).toHaveLength(1);
    expect(screen.getByTestId('antv-pie-chart')).toBeInTheDocument();
    expect(screen.getByText('Top 帖子')).toBeInTheDocument();
    expect(screen.getByText('值得关注的帖子')).toBeInTheDocument();
    expect(screen.getByText('值得关注的示例帖')).toBeInTheDocument();
    expect(screen.getByText('96')).toBeInTheDocument();

    fireEvent.click(screen.getByText('作者 · 2'));
    expect(screen.getByText('作者业务分布')).toBeInTheDocument();
    expect(screen.getByText('地区分布')).toBeInTheDocument();
    expect(screen.queryByText('城市分布')).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: '中国省级块状地图' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /上海：1 位作者，占地区有效样本 100.0%/ })).toBeInTheDocument();
    expect(screen.getByText('Top 作者')).toBeInTheDocument();
    expect(screen.queryByTestId('antv-bar-chart')).not.toBeInTheDocument();
  });

  it('disables metrics that an older snapshot did not persist and explains how to refresh them', () => {
    const legacySummary: DataSummaryPayload = {
      ...summary,
      schema_version: 3,
      content: {
        ...summary.content,
        publish_trend: undefined,
      },
    };

    const { rerender } = render(<DataSummaryV2View summary={summary} />);
    fireEvent.click(screen.getByText('累计点赞'));
    expect(screen.getByRole('radio', { name: '累计点赞' })).toBeChecked();

    rerender(<DataSummaryV2View summary={legacySummary} />);

    expect(screen.getByRole('radio', { name: '发布帖子数' })).toBeEnabled();
    expect(screen.getByRole('radio', { name: '发布帖子数' })).toBeChecked();
    expect(screen.getByRole('radio', { name: '发布作者数' })).toBeDisabled();
    expect(screen.getByRole('radio', { name: '累计点赞' })).toBeDisabled();
    expect(screen.getByText(/该历史摘要只保存了发布帖子数/)).toBeInTheDocument();
  });

  it('uses the simplified author profile module for an author-scoped summary', () => {
    const authorSummary: DataSummaryPayload = {
      ...summary,
      scope: 'author',
      core: { stored_post_count: 3, published_post_count: 9 },
      author_field_coverage: {
        total: 1,
        profile_updated: 1,
        display_name: 1,
        xhs_id: 1,
        followers: 1,
        following: 1,
        likes_collections: 1,
        published_posts: 1,
        bio: 1,
        location: 1,
        avatar: 1,
      },
      author_statistics: undefined,
      author_profile: {
        profile_updated: true,
        last_profile_at: '2026-08-03T08:00:00Z',
        display_name: '测试作者',
        xhs_id: 'test-xhs-id',
        bio: '作者简介',
        location: '上海',
        followers_count: 1200,
        following_count: 42,
        likes_collections_count: 8800,
        published_posts: 9,
        has_avatar: true,
        has_bio: true,
        has_xhs_id: true,
        has_location: true,
        has_followers: true,
      },
    };

    render(<DataSummaryV2View summary={authorSummary} />);
    fireEvent.click(screen.getByText('作者资料'));

    expect(screen.queryByText('作者数据完善度')).not.toBeInTheDocument();
    expect(screen.getByText('测试作者')).toBeInTheDocument();
    expect(screen.queryByText('Top 作者')).not.toBeInTheDocument();
  });
});
