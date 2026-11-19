import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  listSortStorageKey,
  readListSort,
  saveListSort,
  tableSortFromChange,
  tableSortOrder,
  useListSort,
} from './listSortPreferences';

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
const browserStorage = new MemoryStorage();
const supported = ['followers:desc', 'followers:asc', 'updated:desc'] as const;

describe('list sort preferences', () => {
  beforeEach(() => {
    storage.clear();
    browserStorage.clear();
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: browserStorage,
    });
  });

  it('restores a supported sort after a fresh mount', () => {
    expect(saveListSort('authors.global.table', 'updated:desc', supported, 'followers:desc', storage))
      .toBe('updated:desc');
    expect(storage.getItem(listSortStorageKey('authors.global.table'))).toBe('updated:desc');
    expect(readListSort('authors.global.table', supported, 'followers:desc', storage))
      .toBe('updated:desc');
  });

  it('restores the hook state after the list is unmounted and mounted again', () => {
    const first = renderHook(() =>
      useListSort('authors.global.table', supported, 'followers:desc'),
    );
    act(() => first.result.current[1]('updated:desc'));
    first.unmount();

    const second = renderHook(() =>
      useListSort('authors.global.table', supported, 'followers:desc'),
    );
    expect(second.result.current[0]).toBe('updated:desc');
  });

  it('keeps list scopes independent and rejects obsolete values', () => {
    saveListSort('authors.global.table', 'followers:asc', supported, 'followers:desc', storage);
    storage.setItem(listSortStorageKey('authors.project.table'), 'obsolete:desc');

    expect(readListSort('authors.global.table', supported, 'followers:desc', storage))
      .toBe('followers:asc');
    expect(readListSort('authors.project.table', supported, 'followers:desc', storage))
      .toBe('followers:desc');
  });

  it('maps controlled Ant Design sorting in both directions', () => {
    expect(tableSortOrder('updated:desc', 'updated')).toBe('descend');
    expect(tableSortOrder('updated:desc', 'followers')).toBeNull();
    expect(tableSortFromChange('followers', 'ascend', supported, 'followers:desc'))
      .toBe('followers:asc');
    expect(tableSortFromChange('followers', null, supported, 'followers:desc'))
      .toBe('followers:desc');
  });
});
