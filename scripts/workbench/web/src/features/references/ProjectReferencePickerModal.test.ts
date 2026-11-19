import { describe, expect, it } from 'vitest';
import type { Author, Post } from '@/types';
import { filterProjectReferenceCandidates } from './projectReferenceCandidates';

describe('filterProjectReferenceCandidates', () => {
  it('excludes posts already linked to the project and searches remaining posts', () => {
    const posts = [
      { id: 1, title: 'AI 产品复盘', note_id: 'note-1', author_name: '小明' },
      { id: 2, title: '设计系统', note_id: 'note-2', author_name: '小红' },
      { id: 3, title: 'AI 工作流', note_id: 'note-3', author_name: '小李' },
    ] as Post[];

    expect(filterProjectReferenceCandidates(posts, 'post', [1], 'AI').map((post) => post.id)).toEqual([3]);
  });

  it('searches authors by display name, stable ID and Xiaohongshu ID', () => {
    const authors = [
      { id: 1, display_name: 'Eira', author_id: 'author-a', xhs_id: 'eira_ai' },
      { id: 2, display_name: '阿布', author_id: 'author-b', xhs_id: 'abu_design' },
    ] as Author[];

    expect(filterProjectReferenceCandidates(authors, 'author', [], 'abu_design').map((author) => author.id)).toEqual([2]);
  });
});
