import { describe, expect, it } from 'vitest';
import {
  buildAuthorBasicInfoUpdateConfiguration,
  buildAuthorPostUpdateConfiguration,
} from './AuthorUpdateModal';

const author = { author_id: 'author-a', display_name: '测试作者' };

describe('author update configurations', () => {
  it('creates a lightweight profile-only update for the author list action', () => {
    const configuration = buildAuthorBasicInfoUpdateConfiguration(author);

    expect(configuration.author_update?.scopes).toEqual(['basic_info']);
    expect(configuration.limits).toEqual({ discovery: 1, deep: 0 });
    expect(configuration.force_refresh).toBe(true);
  });

  it('updates post preview fields in batches without opening details', () => {
    const configuration = buildAuthorPostUpdateConfiguration(author, {
      scopes: ['preview_posts'],
      previewLimit: 80,
      detailLimit: 5,
    });

    expect(configuration.source.author_ids).toEqual(['author-a']);
    expect(configuration.limits).toEqual({ discovery: 80, deep: 0 });
    expect(configuration.author_update?.scopes).toEqual(['preview_posts']);
  });

  it('keeps batch preview and per-post detail limits separate', () => {
    const configuration = buildAuthorPostUpdateConfiguration(author, {
      scopes: ['preview_posts', 'detailed_posts'],
      previewLimit: 80,
      detailLimit: 5,
    });

    expect(configuration.limits).toEqual({ discovery: 80, deep: 5 });
    expect(configuration.author_update?.scopes).toEqual(['preview_posts', 'detailed_posts']);
  });
});
