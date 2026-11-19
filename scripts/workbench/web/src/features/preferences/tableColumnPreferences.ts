export const TABLE_COLUMN_PREFERENCE_PREFIX = 'xhs-research:table-columns:';

export const TABLE_COLUMN_PREFERENCE_SCOPES = {
  globalAuthors: 'authors.global',
  projectAuthors: 'authors.project',
  globalPosts: 'posts.global',
  authorPosts: 'posts.author',
  projectPosts: 'posts.project',
  globalTasks: 'tasks.global',
  projectTasks: 'tasks.project',
  projectKeywords: 'keywords.project',
} as const;

export type TableColumnPreferenceScope =
  (typeof TABLE_COLUMN_PREFERENCE_SCOPES)[keyof typeof TABLE_COLUMN_PREFERENCE_SCOPES];

export function tableColumnPreferenceKey(scope: TableColumnPreferenceScope): string {
  return `${TABLE_COLUMN_PREFERENCE_PREFIX}${scope}`;
}

export function persistentTableColumns(scope: TableColumnPreferenceScope) {
  return {
    persistenceKey: tableColumnPreferenceKey(scope),
    persistenceType: 'localStorage' as const,
  };
}

export const TABLE_COLUMN_PREFERENCES = {
  globalAuthors: persistentTableColumns(TABLE_COLUMN_PREFERENCE_SCOPES.globalAuthors),
  projectAuthors: persistentTableColumns(TABLE_COLUMN_PREFERENCE_SCOPES.projectAuthors),
  globalPosts: persistentTableColumns(TABLE_COLUMN_PREFERENCE_SCOPES.globalPosts),
  authorPosts: persistentTableColumns(TABLE_COLUMN_PREFERENCE_SCOPES.authorPosts),
  projectPosts: persistentTableColumns(TABLE_COLUMN_PREFERENCE_SCOPES.projectPosts),
  globalTasks: persistentTableColumns(TABLE_COLUMN_PREFERENCE_SCOPES.globalTasks),
  projectTasks: persistentTableColumns(TABLE_COLUMN_PREFERENCE_SCOPES.projectTasks),
  projectKeywords: persistentTableColumns(TABLE_COLUMN_PREFERENCE_SCOPES.projectKeywords),
} as const;
