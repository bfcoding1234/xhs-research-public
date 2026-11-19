import { describe, expect, it } from 'vitest';
import {
  buildPostDetailPath,
  parsePostDetailNavigation,
  postDetailMenuPath,
  postDetailReturnPath,
} from './postNavigation';

describe('post navigation', () => {
  it('keeps a project as the detail source', () => {
    const path = buildPostDetailPath(12, { source: 'project', projectId: 8 });

    expect(path).toBe('/posts/12?from=project&project_id=8');
    expect(parsePostDetailNavigation('?from=project&project_id=8')).toEqual({
      source: 'project',
      projectId: 8,
    });
    expect(postDetailReturnPath({ source: 'project', projectId: 8 })).toBe('/projects/8/posts');
  });

  it('keeps the special personal-author context', () => {
    const navigation = parsePostDetailNavigation(
      '?from=author&author_id=3&base=my-projects',
    );

    expect(navigation).toEqual({ source: 'author', authorId: 3, base: 'my-projects' });
    expect(postDetailReturnPath(navigation)).toBe('/my-projects/posts');
  });

  it('uses the standalone global detail route by default', () => {
    expect(buildPostDetailPath(12, { source: 'global' })).toBe('/posts/12');
    expect(parsePostDetailNavigation('')).toEqual({ source: 'global' });
    expect(postDetailReturnPath({ source: 'global' })).toBe('/posts');
  });

  it('keeps the left navigation on the originating module', () => {
    expect(postDetailMenuPath('?from=project&project_id=8')).toBe('/projects/8/posts');
    expect(postDetailMenuPath('?from=author&author_id=3')).toBe('/authors/3/posts');
    expect(postDetailMenuPath('?from=author&author_id=3&base=my-projects')).toBe('/my-projects/posts');
    expect(postDetailMenuPath('')).toBeUndefined();
  });
});
