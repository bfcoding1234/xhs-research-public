import { useCallback, useEffect, useState } from 'react';

export const POST_PAGE_SIZE_STORAGE_KEY = 'xhs-research:post-page-size';
export const POST_PAGE_SIZE_OPTIONS = [10, 20, 50, 100] as const;
export const DEFAULT_POST_PAGE_SIZE = 20;

function availableLocalStorage(): Storage | undefined {
  try {
    return typeof window === 'undefined' ? undefined : window.localStorage;
  } catch {
    return undefined;
  }
}

export function normalizePostPageSize(value: unknown): number {
  const numeric = Number(value);
  return POST_PAGE_SIZE_OPTIONS.includes(numeric as (typeof POST_PAGE_SIZE_OPTIONS)[number])
    ? numeric
    : DEFAULT_POST_PAGE_SIZE;
}

export function readPostPageSize(storage = availableLocalStorage()): number {
  if (!storage) return DEFAULT_POST_PAGE_SIZE;
  try {
    return normalizePostPageSize(storage.getItem(POST_PAGE_SIZE_STORAGE_KEY));
  } catch {
    return DEFAULT_POST_PAGE_SIZE;
  }
}

export function savePostPageSize(value: unknown, storage = availableLocalStorage()): number {
  const normalized = normalizePostPageSize(value);
  try {
    storage?.setItem(POST_PAGE_SIZE_STORAGE_KEY, String(normalized));
  } catch {
    // The list remains usable when browser storage is unavailable or full.
  }
  return normalized;
}

export function usePostPageSize(): [number, (value: number) => void] {
  const [pageSize, setPageSize] = useState(readPostPageSize);
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === POST_PAGE_SIZE_STORAGE_KEY) {
        setPageSize(normalizePostPageSize(event.newValue));
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);
  const update = useCallback((value: number) => {
    setPageSize(savePostPageSize(value));
  }, []);
  return [pageSize, update];
}
