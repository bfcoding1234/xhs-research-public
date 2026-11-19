import { useCallback, useEffect, useState } from 'react';

export const LIST_SORT_STORAGE_PREFIX = 'xhs-research:list-sort:';

export type PersistentSortOrder = 'ascend' | 'descend' | null;

function availableLocalStorage(): Storage | undefined {
  try {
    return typeof window === 'undefined' ? undefined : window.localStorage;
  } catch {
    return undefined;
  }
}

export function listSortStorageKey(scope: string): string {
  return `${LIST_SORT_STORAGE_PREFIX}${scope}`;
}

export function normalizeListSort<T extends string>(
  value: unknown,
  supportedValues: readonly T[],
  fallback: T,
): T {
  return supportedValues.includes(value as T) ? (value as T) : fallback;
}

export function readListSort<T extends string>(
  scope: string,
  supportedValues: readonly T[],
  fallback: T,
  storage = availableLocalStorage(),
): T {
  if (!storage) return fallback;
  try {
    return normalizeListSort(storage.getItem(listSortStorageKey(scope)), supportedValues, fallback);
  } catch {
    return fallback;
  }
}

export function saveListSort<T extends string>(
  scope: string,
  value: unknown,
  supportedValues: readonly T[],
  fallback: T,
  storage = availableLocalStorage(),
): T {
  const normalized = normalizeListSort(value, supportedValues, fallback);
  try {
    storage?.setItem(listSortStorageKey(scope), normalized);
  } catch {
    // Sorting remains usable in memory when browser storage is unavailable or full.
  }
  return normalized;
}

export function useListSort<T extends string>(
  scope: string,
  supportedValues: readonly T[],
  fallback: T,
): [T, (value: T) => void] {
  const [sort, setSort] = useState(() => readListSort(scope, supportedValues, fallback));

  useEffect(() => {
    const storageKey = listSortStorageKey(scope);
    const onStorage = (event: StorageEvent) => {
      if (event.key === storageKey) {
        setSort(normalizeListSort(event.newValue, supportedValues, fallback));
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, [fallback, scope, supportedValues]);

  const update = useCallback(
    (value: T) => {
      setSort(saveListSort(scope, value, supportedValues, fallback));
    },
    [fallback, scope, supportedValues],
  );

  return [sort, update];
}

export function tableSortOrder(preference: string, field: string): PersistentSortOrder {
  if (preference === `${field}:asc`) return 'ascend';
  if (preference === `${field}:desc`) return 'descend';
  return null;
}

export function tableSortFromChange<T extends string>(
  field: unknown,
  order: PersistentSortOrder | undefined,
  supportedValues: readonly T[],
  fallback: T,
): T {
  if (!order) return fallback;
  const value = `${String(field || '')}:${order === 'ascend' ? 'asc' : 'desc'}`;
  return normalizeListSort(value, supportedValues, fallback);
}
