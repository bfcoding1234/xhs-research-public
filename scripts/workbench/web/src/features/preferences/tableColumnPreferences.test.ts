import { describe, expect, it } from 'vitest';
import {
  TABLE_COLUMN_PREFERENCES,
  TABLE_COLUMN_PREFERENCE_SCOPES,
  persistentTableColumns,
  tableColumnPreferenceKey,
} from './tableColumnPreferences';

describe('tableColumnPreferences', () => {
  it('uses stable localStorage keys for every configurable list schema', () => {
    const preferences = Object.values(TABLE_COLUMN_PREFERENCES);

    expect(preferences).toHaveLength(Object.keys(TABLE_COLUMN_PREFERENCE_SCOPES).length);
    expect(new Set(preferences.map(({ persistenceKey }) => persistenceKey)).size).toBe(
      preferences.length,
    );
    expect(preferences.every(({ persistenceType }) => persistenceType === 'localStorage')).toBe(
      true,
    );
  });

  it('keeps the scope readable in the persisted key', () => {
    expect(tableColumnPreferenceKey(TABLE_COLUMN_PREFERENCE_SCOPES.projectPosts)).toBe(
      'xhs-research:table-columns:posts.project',
    );
    expect(persistentTableColumns(TABLE_COLUMN_PREFERENCE_SCOPES.authorPosts)).toEqual({
      persistenceKey: 'xhs-research:table-columns:posts.author',
      persistenceType: 'localStorage',
    });
  });
});
