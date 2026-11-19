import { describe, expect, it } from 'vitest';
import type { ResearchConfiguration, Task } from '@/types';
import {
  buildResearchConfiguration,
  canonicalAuthorProfileUrl,
  defaultResearchValues,
  invalidAuthorSourceValues,
  normalizeAuthorSourceValues,
  researchValuesFromTask,
  resolveAuthorProfileUrls,
  validateResearchConfiguration,
} from './configuration';

const PROFILE_URL = 'https://www.xiaohongshu.com/user/profile/author-a';

function configuration(values: Partial<ResearchConfiguration> = {}): ResearchConfiguration {
  return {
    topic: 'AI 产品经理内容需求',
    source: { profile_urls: [], keywords: ['AI 产品经理'], user_keywords: [], filters: {} },
    limits: { discovery: 20, deep: 5 },
    keyword_limits: { discovery: 20, deep: 5 },
    author_limits: { discovery: 20, deep: 5 },
    user_limits: { discovery: 5 },
    image_analysis: { mode: 'ocr-only', vision_ratio: 0, vision_count: 0 },
    force_refresh: false,
    ...values,
  };
}

describe('research topic is optional', () => {
  it.each(['keyword', 'author', 'mixed'] as const)('%s 调研允许主题留空', (mode) => {
    expect(() =>
      validateResearchConfiguration(
        configuration({
          topic: '',
          source:
            mode === 'author'
              ? { profile_urls: [PROFILE_URL], keywords: [], filters: {} }
              : { profile_urls: [], keywords: ['AI 产品经理'], filters: {} },
        }),
        mode,
        {},
      ),
    ).not.toThrow();
  });
});

describe('keyword author collection', () => {
  it('默认采集相关作者数为 500，且可以由后台配置覆盖', () => {
    expect(defaultResearchValues({}).keywordAuthorLimit).toBe(500);
    expect(defaultResearchValues({ default_keyword_author_limit: 720 }).keywordAuthorLimit).toBe(720);
  });
  it('开启后复用帖子关键词搜索相关作者，并保存作者总量上限', () => {
    const result = buildResearchConfiguration(
      {
        topic: 'AI 产品经理内容需求',
        keywords: ['AI 产品经理', 'AI 转型'],
        keywordCollectAuthors: true,
        keywordAuthorLimit: 3,
      },
      'keyword',
      { max_authors_per_task: 5 },
    );

    expect(result.source.keywords).toEqual(['AI 产品经理', 'AI 转型']);
    expect(result.source.user_keywords).toEqual(['AI 产品经理', 'AI 转型']);
    expect(result.user_limits).toEqual({ discovery: 3 });
    expect(() =>
      validateResearchConfiguration(result, 'keyword', { max_authors_per_task: 5 }),
    ).not.toThrow();
  });

  it('关闭时不执行关键词搜索作者', () => {
    const result = buildResearchConfiguration(
      {
        topic: 'AI 产品经理内容需求',
        keywords: ['AI 产品经理'],
        keywordCollectAuthors: false,
        keywordAuthorLimit: 3,
      },
      'keyword',
      { max_authors_per_task: 5 },
    );

    expect(result.source.user_keywords).toEqual([]);
  });

  it('可以关闭帖子采集，只按同一组关键词采集作者', () => {
    const result = buildResearchConfiguration(
      {
        topic: 'AI 产品经理作者观察',
        keywords: ['AI 产品经理'],
        keywordCollectPosts: false,
        keywordCollectAuthors: true,
        keywordAuthorLimit: 800,
      },
      'keyword',
      { max_authors_per_task: 5 },
    );

    expect(result.source.keywords).toEqual([]);
    expect(result.source.user_keywords).toEqual(['AI 产品经理']);
    expect(result.source.filters).toEqual({});
    expect(result.user_limits).toEqual({ discovery: 800 });
    expect(() =>
      validateResearchConfiguration(result, 'keyword', { max_authors_per_task: 5 }),
    ).not.toThrow();
  });

  it('帖子和作者都关闭时拒绝创建关键词任务', () => {
    const result = buildResearchConfiguration(
      {
        topic: 'AI 产品经理内容需求',
        keywords: ['AI 产品经理'],
        keywordCollectPosts: false,
        keywordCollectAuthors: false,
      },
      'keyword',
      {},
    );

    expect(() => validateResearchConfiguration(result, 'keyword', {})).toThrow(
      '至少开启采集相关帖子或采集相关作者',
    );
  });

  it('回填仅采作者任务时保留关键词和两个采集开关', () => {
    const task = {
      id: 'task-keyword-authors',
      project_id: null,
      task_type: 'research',
      mode: 'keyword',
      created_from: 'web',
      input_json: {
        topic: 'AI 产品经理作者观察',
        source: {
          profile_urls: [],
          keywords: [],
          user_keywords: ['AI 产品经理'],
          filters: {},
        },
        limits: { discovery: 20, deep: 5 },
        user_limits: { discovery: 80 },
      },
      status: 'completed',
      current_phase: 'completed',
      progress_current: 1,
      progress_total: 1,
      warning_count: 0,
      error_message: '',
      result_json: {},
      created_at: '2026-07-14T00:00:00Z',
      started_at: '2026-07-14T00:00:00Z',
      finished_at: '2026-07-14T00:01:00Z',
    } as Task;

    expect(researchValuesFromTask(task, {})).toMatchObject({
      keywords: ['AI 产品经理'],
      keywordCollectPosts: false,
      keywordCollectAuthors: true,
      keywordAuthorLimit: 80,
    });
  });
});

describe('author source normalization', () => {
  it('把作者 ID 和带查询参数的主页统一成标准主页 URL', () => {
    expect(canonicalAuthorProfileUrl('author-a')).toBe(PROFILE_URL);
    expect(
      canonicalAuthorProfileUrl(
        'https://www.xiaohongshu.com/user/profile/author-a?xsec_token=secret#notes',
      ),
    ).toBe(PROFILE_URL);
    expect(canonicalAuthorProfileUrl('https://example.com/user/profile/author-a')).toBeUndefined();
    expect(
      normalizeAuthorSourceValues([
        'author-a',
        'https://www.xiaohongshu.com/user/profile/author-a?xsec_token=secret',
      ]),
    ).toEqual([PROFILE_URL]);
    expect(resolveAuthorProfileUrls('author-a\nhttps://example.com/not-xhs')).toEqual([
      PROFILE_URL,
    ]);
    expect(invalidAuthorSourceValues('author-a\nhttps://example.com/not-xhs')).toEqual([
      'https://example.com/not-xhs',
    ]);
    expect(invalidAuthorSourceValues('javascript:alert(1)\na')).toEqual([
      'javascript:alert(1)',
      'a',
    ]);
  });

  it('拒绝外站 URL，但允许合法 raw author ID', () => {
    expect(() =>
      validateResearchConfiguration(
        configuration({
          source: {
            profile_urls: ['https://example.com/user/profile/author-a'],
            keywords: [],
            filters: {},
          },
        }),
        'author',
        {},
      ),
    ).toThrow('作者来源只能填写小红书作者主页 URL');

    expect(() =>
      validateResearchConfiguration(
        configuration({
          source: { profile_urls: ['author-a'], keywords: [], filters: {} },
        }),
        'author',
        {},
      ),
    ).not.toThrow();
  });

  it('按 max_author_notes 限制作者默认值和最终任务配置', () => {
    expect(
      defaultResearchValues({
        default_discovery: 80,
        default_deep: 60,
        max_author_notes: 30,
      }),
    ).toMatchObject({ authorDiscovery: 30, authorDeep: 30 });

    const result = buildResearchConfiguration(
      { collector: 'auto', authors: 'author-a', authorDiscovery: 80, authorDeep: 60 },
      'author',
      { max_author_notes: 30 },
    );
    expect(result.author_limits).toEqual({ discovery: 30, deep: 30 });
    expect(result.limits).toEqual({ discovery: 30, deep: 30 });
    expect(result.collector).toBeUndefined();
  });

  it('发现和深度分析数量不再固定封顶为 300', () => {
    expect(
      defaultResearchValues({
        default_discovery: 1200,
        default_deep: 900,
        max_author_notes: 1500,
      }),
    ).toMatchObject({
      keywordDiscovery: 1200,
      keywordDeep: 900,
      authorDiscovery: 1200,
      authorDeep: 900,
    });

    const result = buildResearchConfiguration(
      {
        topic: '大样本内容研究',
        keywords: ['AI 产品经理'],
        keywordDiscovery: 1200,
        keywordDeep: 900,
      },
      'keyword',
      { max_author_notes: 1500 },
    );
    expect(result.keyword_limits).toEqual({ discovery: 1200, deep: 900 });
    expect(() =>
      validateResearchConfiguration(result, 'keyword', { max_author_notes: 1500 }),
    ).not.toThrow();
  });

  it('构建配置时规范化并去重作者来源', () => {
    const result = buildResearchConfiguration(
      {
        topic: '标杆作者内容策略',
        authors: `author-a\n${PROFILE_URL}?xsec_token=secret`,
      },
      'author',
      {},
    );

    expect(result.source.profile_urls).toEqual([PROFILE_URL]);
  });

  it('历史 author_ids 能回填成标准主页 URL', () => {
    const task = {
      id: 'task-1',
      project_id: 1,
      task_type: 'research',
      mode: 'author',
      created_from: 'codex',
      input_json: {
        collector: 'xiaohongshu-cli',
        topic: '',
        source: {
          profile_urls: [`${PROFILE_URL}?xsec_token=secret`],
          author_ids: ['author-a'],
          keywords: [],
          filters: {},
        },
        limits: { discovery: 20, deep: 5 },
      },
      status: 'completed',
      current_phase: 'completed',
      progress_current: 1,
      progress_total: 1,
      warning_count: 0,
      error_message: '',
      result_json: {},
      created_at: '2026-07-11T00:00:00Z',
      started_at: '2026-07-11T00:00:00Z',
      finished_at: '2026-07-11T00:01:00Z',
    } as Task;

    expect(researchValuesFromTask(task, {}).authors).toBe(PROFILE_URL);
    expect(researchValuesFromTask(task, {}).collector).toBeUndefined();
  });

  it('作者采集只接受明确作者，并保存所选采集内容', () => {
    const result = buildResearchConfiguration(
      { authors: 'author-a', authorScopes: ['basic_info'] },
      'author',
      { max_authors_per_task: 5 },
    );

    expect(result.source.user_keywords).toEqual([]);
    expect(result.author_collection).toEqual({ scopes: ['basic_info'] });
    expect(() => validateResearchConfiguration(result, 'author', { max_authors_per_task: 5 })).not.toThrow();
  });
});
