import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, apiService } from './api';

afterEach(() => vi.restoreAllMocks());

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const configuration = {
  collector: 'auto' as const,
  topic: '',
  source: { profile_urls: [], keywords: ['AI'], filters: {} },
  limits: { discovery: 20, deep: 0 },
  keyword_limits: { discovery: 20, deep: 0 },
  author_limits: { discovery: 20, deep: 0 },
  image_analysis: { mode: 'ocr-only' as const, vision_ratio: 0 as const, vision_count: 0 as const },
  force_refresh: false,
};

describe('api client', () => {
  it('loads the backend-only Codex image model catalog', async () => {
    const catalog = {
      available: true,
      models: [{
        id: 'vision-model',
        label: 'Vision Model',
        default_reasoning_effort: 'medium',
        reasoning_efforts: ['low', 'medium', 'high'],
      }],
      error: '',
    };
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(catalog));

    await expect(apiService.visionModels()).resolves.toEqual(catalog);
    expect(fetch.mock.calls[0]?.[0]).toBe('/api/settings/vision-models');
  });

  it('surfaces the backend error message and status', async () => {
    const payload = { error: '项目仍有活跃任务', code: 'active_tasks' };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(payload, 409));
    await expect(api('/api/projects/1')).rejects.toMatchObject({
      message: '项目仍有活跃任务',
      status: 409,
      payload,
    });
  });

  it('returns the exact project deletion summary', async () => {
    const summary = {
      deleted_project_id: 8,
      name: '测试项目',
      deleted_tasks: 0,
      deleted_project_posts: 0,
      deleted_project_authors: 0,
      deleted_reports: 0,
      global_entities_preserved: true,
    };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(summary));

    await expect(apiService.deleteProject(8)).resolves.toEqual(summary);
  });

  it('stores module metadata when creating my project', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      response({ id: 12, name: '我的复盘', config_json: { project_kind: 'my_project' } }, 201),
    );
    await apiService.createProject({
      name: '我的复盘',
      research_type: 'author',
      config: { project_kind: 'my_project' },
    });

    expect(fetch.mock.calls[0]?.[0]).toBe('/api/projects');
    expect(JSON.parse(String(fetch.mock.calls[0]?.[1]?.body))).toMatchObject({
      research_type: 'author',
      config: { project_kind: 'my_project' },
    });
  });

  it('updates a project name and description through the project endpoint', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      response({ id: 12, name: '新名称', description: '新说明' }),
    );

    await apiService.updateProject(12, {
      name: '新名称',
      description: '新说明',
    });

    expect(fetch.mock.calls[0]?.[0]).toBe('/api/projects/12');
    expect(fetch.mock.calls[0]?.[1]).toMatchObject({ method: 'PATCH' });
    expect(JSON.parse(String(fetch.mock.calls[0]?.[1]?.body))).toEqual({
      name: '新名称',
      description: '新说明',
    });
  });

  it('attaches existing posts and authors through the project reference endpoint', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      response({
        project_id: 12,
        post_ids: [3, 4],
        author_ids: [7],
        added_post_count: 2,
        added_author_count: 2,
        post_count: 2,
        author_count: 2,
      }),
    );

    await apiService.addProjectReferences(12, { post_ids: [3, 4], author_ids: [7] });

    expect(fetch.mock.calls[0]?.[0]).toBe('/api/projects/12/references');
    expect(fetch.mock.calls[0]?.[1]).toMatchObject({ method: 'POST' });
    expect(JSON.parse(String(fetch.mock.calls[0]?.[1]?.body))).toEqual({
      post_ids: [3, 4],
      author_ids: [7],
    });
  });

  it('maintains a project keyword list through dedicated endpoints', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response([]));

    await apiService.addProjectKeywords(12, ['AI 产品经理', '职业发展']);
    expect(fetch.mock.calls[0]?.[0]).toBe('/api/projects/12/keywords');
    expect(fetch.mock.calls[0]?.[1]).toMatchObject({ method: 'POST' });
    expect(JSON.parse(String(fetch.mock.calls[0]?.[1]?.body))).toEqual({
      keywords: ['AI 产品经理', '职业发展'],
    });

    await apiService.removeProjectKeywords(12, [4, 5]);
    expect(fetch.mock.calls[1]?.[0]).toBe('/api/projects/12/keywords');
    expect(fetch.mock.calls[1]?.[1]).toMatchObject({ method: 'DELETE' });
    expect(JSON.parse(String(fetch.mock.calls[1]?.[1]?.body))).toEqual({ keyword_ids: [4, 5] });
  });

  it('creates a background AI keyword suggestion task and stores selected results separately', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response({
      id: 'task_keyword',
      status: 'queued',
      url: 'http://127.0.0.1:4318/#/tasks/task_keyword',
    }));

    await apiService.createProjectKeywordSuggestions(12, {
      reference_sources: ['manual', 'ai_generated'],
    });
    expect(fetch.mock.calls[0]?.[0]).toBe('/api/projects/12/keyword-suggestions');
    expect(JSON.parse(String(fetch.mock.calls[0]?.[1]?.body))).toEqual({
      reference_sources: ['manual', 'ai_generated'],
    });

    await apiService.addProjectKeywords(12, ['AI 需求分析'], 'ai_generated');
    expect(JSON.parse(String(fetch.mock.calls[1]?.[1]?.body))).toEqual({
      keywords: ['AI 需求分析'],
      source: 'ai_generated',
    });
  });

  it('loads a filtered project post page instead of the complete post list', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      response({ items: [], total: 0, page: 2, page_size: 50 }),
    );

    await apiService.projectPosts(12, {
      page: 2,
      page_size: 50,
      query: 'AI 工具',
      type: 'image',
      detail: 'detailed',
      ocr: 'completed',
      vision: 'yes',
      media_storage: 'remote',
      popularity: '高热',
      sort: 'likes_desc',
    });

    const url = new URL(String(fetch.mock.calls[0]?.[0]), 'http://localhost');
    expect(url.pathname).toBe('/api/projects/12/posts');
    expect(Object.fromEntries(url.searchParams)).toMatchObject({
      page: '2',
      page_size: '50',
      query: 'AI 工具',
      ocr: 'completed',
      vision: 'yes',
      media_storage: 'remote',
      sort: 'likes_desc',
    });
  });

  it('loads project-wide post completion coverage separately from the paged list', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response({
      total: 12,
      detailed: 7,
      preview: 5,
      ocr_available: 9,
      ocr_completed: 6,
      ocr_pending: 3,
      ocr_other: 3,
    }));

    await apiService.projectPostCoverage(12);

    expect(fetch.mock.calls[0]?.[0]).toBe('/api/projects/12/post-coverage');
  });

  it('loads a paginated global post page and can exclude one project', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      response({ items: [], total: 0, page: 1, page_size: 20 }),
    );

    await apiService.posts({
      page: 1,
      page_size: 20,
      query: 'AI 工具',
      type: 'all',
      detail: 'all',
      ocr: 'other',
      vision: 'no',
      sort: 'updated_desc',
      exclude_project_id: 12,
    });

    const url = new URL(String(fetch.mock.calls[0]?.[0]), 'http://localhost');
    expect(url.pathname).toBe('/api/posts');
    expect(Object.fromEntries(url.searchParams)).toMatchObject({
      page: '1',
      page_size: '20',
      query: 'AI 工具',
      ocr: 'other',
      vision: 'no',
      sort: 'updated_desc',
      exclude_project_id: '12',
    });
  });

  it('removes project references through the project reference endpoint', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      response({
        project_id: 12,
        post_ids: [3],
        author_ids: [7],
        removed_post_count: 4,
        removed_author_count: 1,
        post_count: 0,
        author_count: 0,
      }),
    );

    await apiService.removeProjectReferences(12, {
      post_ids: [3],
      author_ids: [7],
      confirm_remove_author_posts: true,
    });

    expect(fetch.mock.calls[0]?.[0]).toBe('/api/projects/12/references');
    expect(fetch.mock.calls[0]?.[1]).toMatchObject({ method: 'DELETE' });
    expect(JSON.parse(String(fetch.mock.calls[0]?.[1]?.body))).toEqual({
      post_ids: [3],
      author_ids: [7],
      confirm_remove_author_posts: true,
    });
  });

  it('creates an independent task without a project_id', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      response({ id: 'task-independent', status: 'queued', url: '/#/tasks/task-independent' }, 202),
    );

    await apiService.createTask(undefined, 'keyword', configuration);

    expect(fetch.mock.calls[0]?.[0]).toBe('/api/tasks');
    const body = JSON.parse(String(fetch.mock.calls[0]?.[1]?.body));
    expect(body).not.toHaveProperty('project_id');
    expect(body).toMatchObject({ mode: 'keyword', created_from: 'web' });
  });

  it('initializes me from an existing author without requesting a scrape', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      response({ author_id: 7, task: null }, 201),
    );

    await apiService.setupMyAuthor({ author_id: 7 });

    expect(fetch.mock.calls[0]?.[0]).toBe('/api/me/setup');
    expect(fetch.mock.calls[0]?.[1]).toMatchObject({ method: 'POST' });
    expect(JSON.parse(String(fetch.mock.calls[0]?.[1]?.body))).toEqual({ author_id: 7 });
  });

  it('initializes me from a new external author ID', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      response({
        author_id: 9,
        task: { id: 'task-me', status: 'queued', url: '/#/tasks/task-me' },
      }, 201),
    );

    await apiService.setupMyAuthor({ external_author_id: 'new-author-id' });

    expect(JSON.parse(String(fetch.mock.calls[0]?.[1]?.body))).toEqual({
      external_author_id: 'new-author-id',
    });
  });

  it('includes project_id when a task is associated with a project', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      response({ id: 'task-project', status: 'queued', url: '/#/tasks/task-project' }, 202),
    );

    await apiService.createTask(12, 'keyword', configuration);

    expect(JSON.parse(String(fetch.mock.calls[0]?.[1]?.body))).toMatchObject({
      project_id: 12,
      mode: 'keyword',
    });
  });

  it('creates an author report through the author-scoped endpoint', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      response({ id: 'task-author-report', status: 'queued', url: '/#/tasks/task-author-report' }, 202),
    );

    await apiService.startAuthorReport(7, {
      title: '作者报告',
      instructions: '关注选题',
      context_detail: 'detailed',
    });

    expect(fetch.mock.calls[0]?.[0]).toBe('/api/authors/7/ai-report');
    expect(JSON.parse(String(fetch.mock.calls[0]?.[1]?.body))).toEqual({
      created_from: 'web',
      configuration: { title: '作者报告', instructions: '关注选题', context_detail: 'detailed' },
    });
  });
});
