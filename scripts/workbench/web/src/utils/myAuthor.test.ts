import { describe, expect, it } from 'vitest';
import type { Author } from '@/types';
import { MY_AUTHOR_ID_PATTERN, myAuthorOptions } from './myAuthor';

function author(values: Partial<Author> & Pick<Author, 'id' | 'author_id'>): Author {
  return {
    xhs_id: '',
    display_name: '',
    profile_url: '',
    bio: '',
    ip_location: '',
    followers_count: null,
    following_count: null,
    likes_collections_count: null,
    avatar_url: '',
    avatar_local_path: '',
    first_seen_at: '',
    last_seen_at: '',
    last_profile_fetched_at: null,
    updated_at: '',
    ...values,
  };
}

describe('my author options', () => {
  it('uses the display name and searchable Xiaohongshu identity', () => {
    expect(
      myAuthorOptions([
        author({ id: 8, author_id: 'author-8', display_name: '我的昵称', xhs_id: 'xhs888' }),
        author({ id: 9, author_id: 'author-9' }),
      ]),
    ).toEqual([
      { value: 8, label: '我的昵称 · 小红书号 xhs888' },
      { value: 9, label: 'author-9 · 作者 ID author-9' },
    ]);
  });
});

describe('MY_AUTHOR_ID_PATTERN', () => {
  it('accepts stable IDs and rejects nicknames or profile URLs', () => {
    expect(MY_AUTHOR_ID_PATTERN.test('author_123-abc')).toBe(true);
    expect(MY_AUTHOR_ID_PATTERN.test('作者昵称')).toBe(false);
    expect(MY_AUTHOR_ID_PATTERN.test('https://www.xiaohongshu.com/user/profile/abc')).toBe(false);
  });
});
