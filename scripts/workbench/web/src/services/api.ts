import type {
  AppSettings,
  DataRelease,
  DataReleasePreview,
  DataReleaseResult,
  Author,
  DeleteProjectResult,
  Health,
  JsonObject,
  MyAuthorSetupResult,
  Post,
  PostPage,
  PostQuery,
  ProjectPostPage,
  ProjectPostCoverage,
  ProjectPostQuery,
  PostDetailUpdateConfiguration,
  PostCommentCollectionConfiguration,
  PostCommentsPage,
  ProjectAuthorPostConflict,
  ProjectAuthorUpdateConfiguration,
  ProjectReferenceRemovalResult,
  ProjectReferenceIds,
  Project,
  ProjectKeyword,
  ProjectKeywordSource,
  TaskReceipt,
  ProjectReferenceResult,
  Report,
  ReportGenerationConfiguration,
  ReportPresentation,
  ReportPresentationConfiguration,
  ReportStatus,
  ResearchConfiguration,
  ResearchType,
  Stats,
  Task,
  TaskEvent,
  VisionStatus,
  VisionModelCatalog,
  VisionTaskConfiguration,
} from '@/types';

export class ApiError extends Error {
  readonly status: number;
  readonly payload: unknown;

  constructor(message: string, status: number, payload?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload;
  }
}

interface ApiOptions extends Omit<RequestInit, 'body'> {
  body?: unknown;
}

export async function api<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      Accept: 'application/json',
      ...(options.body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...options.headers,
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  const payload = (await response.json().catch(() => ({}))) as { error?: string } & T;
  if (!response.ok) {
    throw new ApiError(payload.error || `请求失败（${response.status}）`, response.status, payload);
  }
  return payload;
}

export function isProjectAuthorPostConflict(
  payload: unknown,
): payload is ProjectAuthorPostConflict {
  return Boolean(
    payload &&
      typeof payload === 'object' &&
      (payload as { code?: unknown }).code === 'author_has_project_posts' &&
      Array.isArray((payload as { authors?: unknown }).authors),
  );
}

export const apiService = {
  health: (signal?: AbortSignal) => api<Health>('/api/health', { signal }),
  stats: (signal?: AbortSignal) => api<Stats>('/api/stats', { signal }),
  settings: (signal?: AbortSignal) => api<AppSettings>('/api/settings', { signal }),
  visionModels: (signal?: AbortSignal) =>
    api<VisionModelCatalog>('/api/settings/vision-models', { signal }),
  updateSettings: (values: Partial<AppSettings>) =>
    api<AppSettings>('/api/settings', { method: 'POST', body: values }),
  dataReleasePreview: (signal?: AbortSignal) =>
    api<DataReleasePreview>('/api/data-release/preview', { signal }),
  dataReleases: (signal?: AbortSignal) => api<DataRelease[]>('/api/data-releases', { signal }),
  publishDataRelease: () =>
    api<DataReleaseResult>('/api/data-release/publish', { method: 'POST', body: { confirm: true } }),
  setupMyAuthor: (values: { author_id: number } | { external_author_id: string }) =>
    api<MyAuthorSetupResult>('/api/me/setup', { method: 'POST', body: values }),
  projects: (signal?: AbortSignal) => api<Project[]>('/api/projects', { signal }),
  posts: (query: PostQuery, signal?: AbortSignal) => {
    const params = new URLSearchParams(
      Object.entries(query)
        .filter(([, value]) => value !== undefined)
        .map(([key, value]) => [key, String(value)]),
    );
    return api<PostPage>(`/api/posts?${params}`, { signal });
  },
  authors: (signal?: AbortSignal) => api<Author[]>('/api/authors', { signal }),
  project: (id: number | string, signal?: AbortSignal) =>
    api<Project>(`/api/projects/${id}`, { signal }),
  createProject: (
    values: Pick<Project, 'name' | 'research_type'> & {
      description?: string;
      config?: JsonObject;
    },
  ) => api<Project>('/api/projects', { method: 'POST', body: { ...values, config: values.config ?? {} } }),
  updateProject: (
    id: number | string,
    values: Pick<Project, 'name' | 'description'>,
  ) => api<Project>(`/api/projects/${id}`, { method: 'PATCH', body: values }),
  deleteProject: (id: number | string, options: { requireEmpty?: boolean } = {}) =>
    api<DeleteProjectResult>(
      `/api/projects/${id}${options.requireEmpty ? '?require_empty=true' : ''}`,
      { method: 'DELETE' },
    ),
  projectPosts: (
    id: number | string,
    query: ProjectPostQuery,
    signal?: AbortSignal,
  ) => {
    const params = new URLSearchParams(
      Object.entries(query).map(([key, value]) => [key, String(value)]),
    );
    return api<ProjectPostPage>(`/api/projects/${id}/posts?${params}`, { signal });
  },
  projectPostCoverage: (id: number | string, signal?: AbortSignal) =>
    api<ProjectPostCoverage>(`/api/projects/${id}/post-coverage`, { signal }),
  projectReferenceIds: (id: number | string, signal?: AbortSignal) =>
    api<ProjectReferenceIds>(`/api/projects/${id}/reference-ids`, { signal }),
  projectKeywords: (id: number | string, signal?: AbortSignal) =>
    api<ProjectKeyword[]>(`/api/projects/${id}/keywords`, { signal }),
  addProjectKeywords: (
    id: number | string,
    keywords: string[],
    source?: ProjectKeywordSource,
  ) =>
    api<ProjectKeyword[]>(`/api/projects/${id}/keywords`, {
      method: 'POST', body: { keywords, ...(source ? { source } : {}) },
    }),
  createProjectKeywordSuggestions: (
    id: number | string,
    values: { reference_sources: ProjectKeywordSource[] },
  ) =>
    api<TaskReceipt>(`/api/projects/${id}/keyword-suggestions`, {
      method: 'POST',
      body: values,
    }),
  removeProjectKeywords: (id: number | string, keywordIds: number[]) =>
    api<ProjectKeyword[]>(`/api/projects/${id}/keywords`, {
      method: 'DELETE', body: { keyword_ids: keywordIds },
    }),
  projectAuthors: (id: number | string, signal?: AbortSignal) =>
    api<Author[]>(`/api/projects/${id}/authors`, { signal }),
  addProjectReferences: (
    id: number | string,
    values: { post_ids?: number[]; author_ids?: number[] },
  ) =>
    api<ProjectReferenceResult>(`/api/projects/${id}/references`, {
      method: 'POST',
      body: { post_ids: values.post_ids ?? [], author_ids: values.author_ids ?? [] },
    }),
  removeProjectReferences: (
    id: number | string,
    values: {
      post_ids?: number[];
      author_ids?: number[];
      confirm_remove_author_posts?: boolean;
    },
  ) =>
    api<ProjectReferenceRemovalResult>(`/api/projects/${id}/references`, {
      method: 'DELETE',
      body: {
        post_ids: values.post_ids ?? [],
        author_ids: values.author_ids ?? [],
        confirm_remove_author_posts: Boolean(values.confirm_remove_author_posts),
      },
    }),
  projectReports: (id: number | string, signal?: AbortSignal) =>
    api<Report[]>(`/api/projects/${id}/reports`, { signal }),
  projectTasks: (id: number | string, signal?: AbortSignal) =>
    api<Task[]>(`/api/projects/${id}/tasks`, { signal }),
  projectVisionStatus: (id: number | string, signal?: AbortSignal) =>
    api<VisionStatus>(`/api/projects/${id}/vision-status`, { signal }),
  projectReportStatus: (id: number | string, signal?: AbortSignal) =>
    api<ReportStatus>(`/api/projects/${id}/report-status`, { signal }),
  post: (id: number | string, signal?: AbortSignal) =>
    api<Post>(`/api/posts/${id}`, { signal }),
  postComments: (id: number | string, page = 1, pageSize = 20, signal?: AbortSignal) =>
    api<PostCommentsPage>(`/api/posts/${id}/comments?page=${page}&page_size=${pageSize}`, { signal }),
  startPostCommentCollection: (
    id: number | string,
    configuration: PostCommentCollectionConfiguration,
  ) =>
    api<TaskReceipt>(`/api/posts/${id}/comment-tasks`, {
      method: 'POST',
      body: { created_from: 'web', configuration },
    }),
  author: (id: number | string, signal?: AbortSignal) =>
    api<Author>(`/api/authors/${id}`, { signal }),
  authorVisionStatus: (id: number | string, signal?: AbortSignal) =>
    api<VisionStatus>(`/api/authors/${id}/vision-status`, { signal }),
  authorReports: (id: number | string, signal?: AbortSignal) =>
    api<Report[]>(`/api/authors/${id}/reports`, { signal }),
  authorReportStatus: (id: number | string, signal?: AbortSignal) =>
    api<ReportStatus>(`/api/authors/${id}/report-status`, { signal }),
  tasks: (signal?: AbortSignal) => api<Task[]>('/api/tasks', { signal }),
  task: (id: string, signal?: AbortSignal) => api<Task>(`/api/tasks/${id}`, { signal }),
  taskEvents: (id: string, after = 0, signal?: AbortSignal) =>
    api<TaskEvent[]>(`/api/tasks/${id}/events?after=${after}`, { signal }),
  createTask: (
    projectId: number | undefined,
    mode: ResearchType,
    configuration: ResearchConfiguration,
  ) =>
    api<TaskReceipt>('/api/tasks', {
      method: 'POST',
      body: {
        ...(projectId === undefined ? {} : { project_id: projectId }),
        mode,
        created_from: 'web',
        run_mode: 'incremental',
        ...configuration,
      },
    }),
  rerunProject: (
    projectId: number,
    sourceTaskId: string,
    configuration: ResearchConfiguration,
  ) =>
    api<TaskReceipt>(`/api/projects/${projectId}/run`, {
      method: 'POST',
      body: {
        source_task_id: sourceTaskId,
        configuration,
        force_refresh: configuration.force_refresh,
      },
    }),
  cancelTask: (id: string) =>
    api<{ id: string; status: 'cancelled' }>(`/api/tasks/${id}/cancel`, {
      method: 'POST',
      body: {},
    }),
  resumeTask: (id: string) =>
    api<{ id: string; status: 'resuming' }>(`/api/tasks/${id}/resume`, {
      method: 'POST',
      body: {},
    }),
  retryTask: (id: string) =>
    api<TaskReceipt>(`/api/tasks/${id}/retry`, { method: 'POST', body: {} }),
  startVision: (projectId: number, configuration: VisionTaskConfiguration) =>
    api<TaskReceipt>(`/api/projects/${projectId}/vision`, {
      method: 'POST',
      body: { created_from: 'web', configuration },
    }),
  startAuthorVision: (authorId: number, configuration: VisionTaskConfiguration) =>
    api<TaskReceipt>(`/api/authors/${authorId}/vision`, {
      method: 'POST',
      body: { created_from: 'web', configuration },
    }),
  startReport: (projectId: number, configuration: ReportGenerationConfiguration) =>
    api<TaskReceipt>(`/api/projects/${projectId}/ai-report`, {
      method: 'POST',
      body: { created_from: 'web', configuration },
    }),
  startAuthorReport: (authorId: number, configuration: ReportGenerationConfiguration) =>
    api<TaskReceipt>(`/api/authors/${authorId}/ai-report`, {
      method: 'POST',
      body: { created_from: 'web', configuration },
    }),
  reportPresentations: (target: { type: 'project' | 'author'; id: number }, reportId: number) =>
    api<ReportPresentation[]>(
      `/api/${target.type === 'project' ? 'projects' : 'authors'}/${target.id}/reports/${reportId}/presentations`,
    ),
  startReportPresentation: (
    target: { type: 'project' | 'author'; id: number },
    reportId: number,
    configuration: ReportPresentationConfiguration,
  ) =>
    api<TaskReceipt>(
      `/api/${target.type === 'project' ? 'projects' : 'authors'}/${target.id}/reports/${reportId}/presentations`,
      { method: 'POST', body: { created_from: 'web', configuration } },
    ),
  reportPresentationHtmlUrl: (presentationId: number, download = false) =>
    `/api/report-presentations/${presentationId}/html${download ? '?download=1' : ''}`,
  generateProjectDataSummary: (projectId: number) =>
    api<Report>(`/api/projects/${projectId}/data-summary`, {
      method: 'POST',
      body: {},
    }),
  generateAuthorDataSummary: (authorId: number) =>
    api<Report>(`/api/authors/${authorId}/data-summary`, {
      method: 'POST',
      body: {},
    }),
  startProjectAuthorUpdates: (
    projectId: number | string,
    configuration: ProjectAuthorUpdateConfiguration,
  ) =>
    api<TaskReceipt>(`/api/projects/${projectId}/author-updates`, {
      method: 'POST',
      body: { created_from: 'web', configuration },
    }),
  startPostDetailUpdate: (configuration: PostDetailUpdateConfiguration) =>
    api<TaskReceipt>('/api/post-detail-updates', {
      method: 'POST',
      body: { created_from: 'web', configuration },
    }),
};
