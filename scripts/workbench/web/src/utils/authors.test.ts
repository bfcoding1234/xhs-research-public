import { describe, expect, it } from 'vitest';
import type { Author } from '@/types';
import {
  authorPostCollectionStats,
  authorProfileUrl,
  formatAuthorPostCollectionStats,
  formatAuthorPostCoverage,
  rankCandidateAuthors,
  recommendedAuthorIds,
  sortAuthorsByFollowersDesc,
  storedAuthorPostCount,
} from './authors';

function author(values: Partial<Author> & Pick<Author, 'author_id' | 'display_name'>): Author {
  return {
    id: 1,
    xhs_id: '',
    profile_url: '',
    bio: '',
    ip_location: '',
    followers_count: 0,
    following_count: 0,
    likes_collections_count: 0,
    avatar_url: '',
    avatar_local_path: '',
    first_seen_at: '',
    last_seen_at: '',
    last_profile_fetched_at: null,
    updated_at: '',
    ...values,
  };
}

describe('author ranking', () => {
  it('sorts the global author list by follower count descending', () => {
    expect(
      sortAuthorsByFollowersDesc([
        author({ author_id: 'small', display_name: '小号', followers_count: 120 }),
        author({ author_id: 'large', display_name: '大号', followers_count: 80_000 }),
        author({ author_id: 'unknown', display_name: '未知', followers_count: null }),
      ]).map((item) => item.author_id),
    ).toEqual(['large', 'small', 'unknown']);
  });

  it('prioritizes visible content performance before account size', () => {
    const contentLeader = author({
      author_id: 'content',
      display_name: '内容强',
      hot_post_count: 8,
      peak_popularity_percentile: 1,
      followers_count: 1_000,
    });
    const accountLeader = author({
      author_id: 'account',
      display_name: '账号大',
      hot_post_count: 0,
      peak_popularity_percentile: 0.1,
      followers_count: 1_000_000,
      likes_collections_count: 10_000_000,
    });
    expect(rankCandidateAuthors([accountLeader, contentLeader])[0]?.author_id).toBe('content');
    expect(recommendedAuthorIds([accountLeader, contentLeader], 1)).toEqual(new Set(['content']));
  });
});

describe('author profile URL', () => {
  it('prefers the stored profile URL', () => {
    expect(
      authorProfileUrl({
        author_id: 'author-a',
        profile_url: ' https://www.xiaohongshu.com/user/profile/author-a?xsec_token=token ',
      }),
    ).toBe('https://www.xiaohongshu.com/user/profile/author-a?xsec_token=token');
  });

  it('builds a profile URL from the author ID when needed', () => {
    expect(authorProfileUrl({ author_id: '作者/a', profile_url: '' })).toBe(
      'https://www.xiaohongshu.com/user/profile/%E4%BD%9C%E8%80%85%2Fa',
    );
  });
});

describe('author post coverage', () => {
  it('formats stored and total post counts as a ratio', () => {
    const value = author({
      author_id: 'coverage',
      display_name: '覆盖率作者',
      stored_post_count: 500,
      total_post_count: 1000,
    });

    expect(storedAuthorPostCount(value)).toBe(500);
    expect(formatAuthorPostCoverage(value)).toBe('500/1000');
  });

  it('does not pretend the stored count is the unknown profile total', () => {
    const value = author({
      author_id: 'unknown-total',
      display_name: '总数未知',
      posts: [{ id: 1 }, { id: 2 }] as Author['posts'],
    });

    expect(formatAuthorPostCoverage(value)).toBe('2/—');
  });

  it('counts collected details and current image understanding results separately', () => {
    const value = author({
      author_id: 'collection-stats',
      display_name: '采集统计作者',
      total_post_count: 1000,
      posts: [
        { id: 1, detail_level: 'card', has_vision_result: 0 },
        { id: 2, detail_level: 'detail', has_vision_result: 1 },
        { id: 3, detail_level: 'media', has_vision_result: 1 },
      ] as Author['posts'],
    });

    const stats = authorPostCollectionStats(value);
    expect(stats).toEqual({
      publishedPostCount: 1000,
      storedPostCount: 3,
      detailedPostCount: 2,
      visionAnalyzedPostCount: 2,
    });
    expect(formatAuthorPostCollectionStats(stats)).toBe('2/2/3/1000');
  });
});
