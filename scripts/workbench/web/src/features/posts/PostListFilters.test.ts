import { describe, expect, it } from 'vitest';
import {
  DEFAULT_POST_LIST_FILTERS,
  filterPostList,
  filterPostsByMediaStorage,
} from './PostListFilters';

const posts = [
  {
    id: 1,
    note_id: 'note-one',
    title: 'Agent 产品设计',
    author_name: '点点',
    note_type: 'image',
    detail_level: 'detail',
    has_ocr_result: 1,
    ocr_status: 'completed' as const,
    has_vision_result: 1,
    media_storage_status: 'remote' as const,
  },
  {
    id: 2,
    note_id: 'note-two',
    title: '模型评测',
    author_name: 'Allen',
    note_type: 'video',
    detail_level: 'card',
    has_ocr_result: 0,
    ocr_status: 'other' as const,
    has_vision_result: 0,
    media_storage_status: 'local' as const,
  },
];

describe('filterPostList', () => {
  it('searches across title, author and note ID', () => {
    expect(filterPostList(posts, { ...DEFAULT_POST_LIST_FILTERS, query: '点点' })).toHaveLength(1);
    expect(filterPostList(posts, { ...DEFAULT_POST_LIST_FILTERS, query: 'note-two' })[0]?.id).toBe(2);
  });

  it('combines type, detail, OCR and vision filters', () => {
    expect(filterPostList(posts, {
      query: '',
      type: 'image',
      detail: 'detailed',
      ocr: 'completed',
      vision: 'yes',
    }).map((post) => post.id)).toEqual([1]);
    expect(filterPostList(posts, {
      query: '',
      type: 'video',
      detail: 'preview',
      ocr: 'other',
      vision: 'no',
    }).map((post) => post.id)).toEqual([2]);
  });

  it('filters author posts by their body-image storage status', () => {
    expect(filterPostsByMediaStorage(posts, 'remote').map((post) => post.id)).toEqual([1]);
    expect(filterPostsByMediaStorage(posts, 'local').map((post) => post.id)).toEqual([2]);
    expect(filterPostsByMediaStorage(posts, 'all')).toEqual(posts);
  });
});
