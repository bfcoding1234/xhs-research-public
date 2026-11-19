export const queryKeys = {
  health: ['health'] as const,
  stats: ['stats'] as const,
  settings: ['settings'] as const,
  visionModels: ['settings', 'vision-models'] as const,
  projects: ['projects'] as const,
  posts: ['posts'] as const,
  authors: ['authors'] as const,
  project: (id: number | string) => ['project', String(id)] as const,
  projectPosts: (id: number | string, query?: object) =>
    query
      ? (['project', String(id), 'posts', query] as const)
      : (['project', String(id), 'posts'] as const),
  projectPostCoverage: (id: number | string) =>
    ['project', String(id), 'post-coverage'] as const,
  projectReferenceIds: (id: number | string) =>
    ['project', String(id), 'reference-ids'] as const,
  projectKeywords: (id: number | string) => ['project', String(id), 'keywords'] as const,
  projectAuthors: (id: number | string) => ['project', String(id), 'authors'] as const,
  projectReports: (id: number | string) => ['project', String(id), 'reports'] as const,
  projectTasks: (id: number | string) => ['project', String(id), 'tasks'] as const,
  projectVision: (id: number | string) => ['project', String(id), 'vision'] as const,
  projectReportStatus: (id: number | string) => ['project', String(id), 'report-status'] as const,
  post: (id: number | string) => ['post', String(id)] as const,
  postComments: (id: number | string, page?: number, pageSize?: number) =>
    ['post', String(id), 'comments', page ?? 1, pageSize ?? 20] as const,
  author: (id: number | string) => ['author', String(id)] as const,
  authorVision: (id: number | string) => ['author', String(id), 'vision'] as const,
  authorReports: (id: number | string) => ['author', String(id), 'reports'] as const,
  authorReportStatus: (id: number | string) => ['author', String(id), 'report-status'] as const,
  reportPresentations: (type: 'project' | 'author', id: number | string, reportId: number | string) =>
    [type, String(id), 'report', String(reportId), 'presentations'] as const,
  tasks: ['tasks'] as const,
  task: (id: string) => ['task', id] as const,
  taskEvents: (id: string) => ['task', id, 'events'] as const,
};

export function projectFinalSyncQueryKeys(id: number | string) {
  return [
    queryKeys.project(id),
    queryKeys.projectKeywords(id),
    queryKeys.projectPosts(id),
    queryKeys.projectPostCoverage(id),
    queryKeys.projectAuthors(id),
    queryKeys.projectReports(id),
    queryKeys.projectVision(id),
    queryKeys.projectReportStatus(id),
    queryKeys.projectTasks(id),
  ] as const;
}
