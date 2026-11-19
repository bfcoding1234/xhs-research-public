import { beforeEach, describe, expect, it } from 'vitest';
import {
  DEFAULT_POST_PAGE_SIZE,
  POST_PAGE_SIZE_STORAGE_KEY,
  readPostPageSize,
  savePostPageSize,
} from './postListPreferences';

class MemoryStorage implements Storage {
  private values = new Map<string, string>();

  get length() {
    return this.values.size;
  }

  clear() {
    this.values.clear();
  }

  getItem(key: string) {
    return this.values.get(key) ?? null;
  }

  key(index: number) {
    return [...this.values.keys()][index] ?? null;
  }

  removeItem(key: string) {
    this.values.delete(key);
  }

  setItem(key: string, value: string) {
    this.values.set(key, value);
  }
}

const storage = new MemoryStorage();

describe('post list page-size preference', () => {
  beforeEach(() => storage.clear());

  it('persists a supported page size across post-list mounts', () => {
    expect(savePostPageSize(50, storage)).toBe(50);
    expect(storage.getItem(POST_PAGE_SIZE_STORAGE_KEY)).toBe('50');
    expect(readPostPageSize(storage)).toBe(50);
  });

  it('falls back when stored values are unsupported or malformed', () => {
    storage.setItem(POST_PAGE_SIZE_STORAGE_KEY, '37');
    expect(readPostPageSize(storage)).toBe(DEFAULT_POST_PAGE_SIZE);

    storage.setItem(POST_PAGE_SIZE_STORAGE_KEY, 'not-a-number');
    expect(readPostPageSize(storage)).toBe(DEFAULT_POST_PAGE_SIZE);
  });
});
