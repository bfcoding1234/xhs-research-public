import type { Author } from '@/types';

const numeric = (value: unknown) => Math.max(0, Number(value) || 0);

function countPart(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  const number = Number(value);
  return Number.isFinite(number) ? String(Math.max(0, Math.trunc(number))) : '—';
}

export function storedAuthorPostCount(
  author: Pick<Author, 'stored_post_count' | 'post_count' | 'posts'>,
): number {
  return numeric(author.stored_post_count ?? author.posts?.length ?? author.post_count);
}

export function formatAuthorPostCoverage(
  author: Pick<Author, 'stored_post_count' | 'total_post_count' | 'post_count' | 'posts'>,
): string {
  return `${countPart(storedAuthorPostCount(author))}/${countPart(author.total_post_count)}`;
}

export interface AuthorPostCollectionStats {
  publishedPostCount: number | null;
  storedPostCount: number;
  detailedPostCount: number;
  visionAnalyzedPostCount: number;
}

export function authorPostCollectionStats(
  author: Pick<Author, 'stored_post_count' | 'total_post_count' | 'post_count' | 'posts'>,
): AuthorPostCollectionStats {
  const posts = author.posts ?? [];
  return {
    publishedPostCount:
      author.total_post_count === null || author.total_post_count === undefined
        ? null
        : numeric(author.total_post_count),
    storedPostCount: storedAuthorPostCount(author),
    detailedPostCount: posts.filter(
      (post) => Boolean(post.detail_level) && post.detail_level !== 'card',
    ).length,
    visionAnalyzedPostCount: posts.filter((post) => Boolean(Number(post.has_vision_result))).length,
  };
}

export function formatAuthorPostCollectionStats(stats: AuthorPostCollectionStats): string {
  return [
    stats.detailedPostCount,
    stats.visionAnalyzedPostCount,
    stats.storedPostCount,
    stats.publishedPostCount,
  ]
    .map(countPart)
    .join('/');
}

export function sortAuthorsByFollowersDesc(authors: Author[] = []): Author[] {
  return [...authors].sort(
    (left, right) =>
      numeric(right.followers_count) - numeric(left.followers_count) ||
      String(left.display_name || left.author_id).localeCompare(
        String(right.display_name || right.author_id),
        'zh-CN',
      ),
  );
}

export function authorProfileUrl(author: Pick<Author, 'author_id' | 'profile_url'>): string {
  return (
    author.profile_url?.trim() ||
    `https://www.xiaohongshu.com/user/profile/${encodeURIComponent(author.author_id)}`
  );
}

function normalizedLog(value: number, maximum: number): number {
  return maximum ? Math.log10(value + 1) / Math.log10(maximum + 1) : 0;
}

export function rankCandidateAuthors(authors: Author[] = []): Author[] {
  const prepared = authors.map((author) => ({
    ...author,
    hot_post_count: numeric(author.hot_post_count),
    peak_popularity_percentile: Math.min(1, numeric(author.peak_popularity_percentile)),
    followers_count: numeric(author.followers_count),
    likes_collections_count: numeric(author.likes_collections_count),
  }));
  const maximum = prepared.reduce(
    (value, author) => ({
      hot: Math.max(value.hot, author.hot_post_count),
      followers: Math.max(value.followers, author.followers_count),
      likes: Math.max(value.likes, author.likes_collections_count),
    }),
    { hot: 0, followers: 0, likes: 0 },
  );
  return prepared
    .map((author) => ({
      ...author,
      selection_priority: Math.round(
        100 *
          (normalizedLog(author.hot_post_count, maximum.hot) * 0.4 +
            author.peak_popularity_percentile * 0.3 +
            normalizedLog(author.followers_count, maximum.followers) * 0.2 +
            normalizedLog(author.likes_collections_count, maximum.likes) * 0.1),
      ),
    }))
    .sort(
      (left, right) =>
        (right.selection_priority || 0) - (left.selection_priority || 0) ||
        (right.hot_post_count || 0) - (left.hot_post_count || 0) ||
        (right.peak_popularity_percentile || 0) - (left.peak_popularity_percentile || 0) ||
        (right.followers_count || 0) - (left.followers_count || 0) ||
        (right.likes_collections_count || 0) - (left.likes_collections_count || 0) ||
        String(left.display_name || left.author_id).localeCompare(
          String(right.display_name || right.author_id),
          'zh-CN',
        ),
    );
}

export function recommendedAuthorIds(authors: Author[] = [], limit = 5): Set<string> {
  return new Set(
    rankCandidateAuthors(authors)
      .slice(0, Math.max(0, limit))
      .map((author) => author.author_id),
  );
}
