import type {
  AppSettings,
  ResearchConfiguration,
  ResearchLimits,
  ResearchType,
  Task,
} from '@/types';
import type { ResearchFormValues, SourceFieldValue } from './types';

const DEFAULT_SOURCE_LIMIT = 5;
const MAX_CONFIGURABLE_SOURCE_LIMIT = 20;
const XHS_PROFILE_ORIGIN = 'https://www.xiaohongshu.com';

type SourceLimitKey = 'max_keywords_per_task' | 'max_authors_per_task';

function finiteInteger(value: unknown, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.trunc(parsed) : fallback;
}

function unique(values: string[]): string[] {
  return [...new Set(values)];
}

export function splitSourceValues(value: SourceFieldValue | unknown): string[] {
  const values = Array.isArray(value) ? value : [value];
  return unique(
    values
      .flatMap((item) => String(item ?? '').split(/[\n,，;；]/))
      .map((item) => item.trim())
      .filter(Boolean),
  );
}

function decodedAuthorId(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function validAuthorId(value: string): string | undefined {
  const authorId = decodedAuthorId(value).trim();
  return /^[A-Za-z0-9_-]{3,128}$/.test(authorId) ? authorId : undefined;
}

function authorIdFromSource(value: string): string | undefined {
  const source = value.trim();
  if (!source) return undefined;

  const urlValue = /^(?:www\.)?xiaohongshu\.com\//i.test(source)
    ? `https://${source}`
    : source.startsWith('//')
      ? `https:${source}`
      : source;

  if (/^https?:\/\//i.test(urlValue)) {
    try {
      const url = new URL(urlValue);
      const hostname = url.hostname.toLocaleLowerCase('en-US');
      if (hostname !== 'xiaohongshu.com' && !hostname.endsWith('.xiaohongshu.com')) {
        return undefined;
      }
      const match = url.pathname.match(/^\/user\/profile\/([^/]+)/i);
      return match?.[1] ? validAuthorId(match[1]) : undefined;
    } catch {
      return undefined;
    }
  }

  if (/^[a-z][a-z\d+.-]*:\/\//i.test(source) || /[:/?#\\\s]/.test(source)) {
    return undefined;
  }
  return validAuthorId(source);
}

export function invalidAuthorSourceValues(value: SourceFieldValue | unknown): string[] {
  return splitSourceValues(value).filter((source) => !authorIdFromSource(source));
}

export function canonicalAuthorProfileUrl(value: string): string | undefined {
  const authorId = authorIdFromSource(value);
  return authorId
    ? `${XHS_PROFILE_ORIGIN}/user/profile/${encodeURIComponent(authorId)}`
    : undefined;
}

export function resolveAuthorProfileUrls(value: SourceFieldValue | unknown): string[] {
  return unique(
    splitSourceValues(value)
      .map(canonicalAuthorProfileUrl)
      .filter((profileUrl): profileUrl is string => Boolean(profileUrl)),
  );
}

export function normalizeAuthorSourceValues(value: SourceFieldValue | unknown): string[] {
  return unique(
    splitSourceValues(value).map((source) => canonicalAuthorProfileUrl(source) ?? source),
  );
}

export function sourceLimit(settings: Partial<AppSettings>, key: SourceLimitKey): number {
  return Math.max(
    1,
    Math.min(MAX_CONFIGURABLE_SOURCE_LIMIT, finiteInteger(settings[key], DEFAULT_SOURCE_LIMIT)),
  );
}

export function defaultResearchValues(settings: Partial<AppSettings>): ResearchFormValues {
  const defaultDiscovery = finiteInteger(settings.default_discovery, 20);
  const defaultDeep = finiteInteger(settings.default_deep, 5);
  const authorMaximum = maxAuthorNotes(settings);
  const authorDiscovery = Math.min(defaultDiscovery, authorMaximum);
  return {
    mode: 'keyword',
    keywords: [],
    keywordCollectPosts: true,
    keywordCollectAuthors: false,
    keywordAuthorLimit: Math.max(1, finiteInteger(settings.default_keyword_author_limit, 500)),
    authors: '',
    userKeywords: [],
    userDiscovery: Math.min(5, sourceLimit(settings, 'max_authors_per_task')),
    keywordDiscovery: defaultDiscovery,
    keywordDeep: Math.min(defaultDeep, defaultDiscovery),
    authorDiscovery,
    authorDeep: Math.min(defaultDeep, authorDiscovery, authorMaximum),
    authorScopes: ['basic_info'],
    sort: '综合',
    publishTime: '不限',
    forceRefresh: false,
  };
}

export function maxAuthorNotes(settings: Partial<AppSettings>): number {
  return Math.max(1, finiteInteger(settings.max_author_notes, 300));
}

function limitsFromValues(
  discovery: unknown,
  deep: unknown,
  fallback: ResearchLimits,
): ResearchLimits {
  return {
    discovery: finiteInteger(discovery, fallback.discovery),
    deep: finiteInteger(deep, fallback.deep),
  };
}

export function buildResearchConfiguration(
  values: ResearchFormValues,
  mode: ResearchType,
  settings: Partial<AppSettings>,
): ResearchConfiguration {
  const defaults = defaultResearchValues(settings);
  const defaultLimits = {
    discovery: defaults.keywordDiscovery ?? 20,
    deep: defaults.keywordDeep ?? 5,
  };
  const keywordLimits = limitsFromValues(
    values.keywordDiscovery,
    values.keywordDeep,
    defaultLimits,
  );
  const requestedAuthorLimits = limitsFromValues(
    values.authorDiscovery,
    values.authorDeep,
    defaultLimits,
  );
  const authorMaximum = maxAuthorNotes(settings);
  const authorLimits = {
    discovery: Math.min(requestedAuthorLimits.discovery, authorMaximum),
    deep: Math.min(requestedAuthorLimits.deep, authorMaximum),
  };
  const rawKeywords = mode === 'author'
    ? []
    : splitSourceValues([...(splitSourceValues(values.keywords)), ...(splitSourceValues(values.projectKeywords))]);
  const collectKeywordPosts = mode !== 'keyword' || values.keywordCollectPosts !== false;
  const collectKeywordAuthors = mode === 'keyword' && Boolean(values.keywordCollectAuthors);

  return {
    topic: String(values.topic ?? '').trim(),
    source: {
      profile_urls: mode === 'keyword' ? [] : normalizeAuthorSourceValues(values.authors),
      keywords: collectKeywordPosts ? rawKeywords : [],
      user_keywords: collectKeywordAuthors
        ? rawKeywords
        : mode === 'keyword'
          ? []
          : splitSourceValues(values.userKeywords),
      filters:
        mode === 'author' || !collectKeywordPosts
          ? {}
          : {
              sort: String(values.sort || '综合'),
              publish_time: String(values.publishTime || '不限'),
            },
    },
    limits: mode === 'author' ? authorLimits : keywordLimits,
    keyword_limits: keywordLimits,
    author_limits: authorLimits,
    user_limits: {
      discovery: collectKeywordAuthors
        ? finiteInteger(values.keywordAuthorLimit, defaults.keywordAuthorLimit ?? 5)
        : finiteInteger(values.userDiscovery, defaults.userDiscovery ?? 5),
    },
    author_collection:
      mode === 'author'
        ? { scopes: (values.authorScopes ?? ['basic_info']).filter(
          (scope): scope is 'basic_info' | 'posts' => scope === 'basic_info' || scope === 'posts',
        ) }
        : undefined,
    image_analysis: { mode: 'ocr-only', vision_ratio: 0, vision_count: 0 },
    force_refresh: Boolean(values.forceRefresh),
  };
}

function validateLimits(
  label: string,
  limits: ResearchLimits,
  maximumDiscovery?: number,
): void {
  if (limits.discovery < 1) {
    throw new Error(`${label}发现数量不能小于 1`);
  }
  if (maximumDiscovery !== undefined && limits.discovery > maximumDiscovery) {
    throw new Error(`${label}发现数量不能超过作者采集硬上限 ${maximumDiscovery}`);
  }
  if (limits.deep < 0) {
    throw new Error(`${label}深度分析数量不能小于 0`);
  }
  if (limits.deep > limits.discovery) {
    throw new Error(`${label}深度分析数量不能超过发现数量`);
  }
}

export function validateSourceCounts(
  configuration: ResearchConfiguration,
  settings: Partial<AppSettings>,
): void {
  const keywordLimit = sourceLimit(settings, 'max_keywords_per_task');
  const authorLimit = sourceLimit(settings, 'max_authors_per_task');
  const authorCount = normalizeAuthorSourceValues([
    ...configuration.source.profile_urls,
    ...(configuration.source.author_ids ?? []),
  ]).length;

  if (configuration.source.keywords.length > keywordLimit) {
    throw new Error(`本次最多可使用 ${keywordLimit} 个关键词，请删减后再继续`);
  }
  if ((configuration.source.user_keywords ?? []).length > keywordLimit) {
    throw new Error(`本次最多可使用 ${keywordLimit} 个用户关键词，请删减后再继续`);
  }
  if (authorCount > authorLimit) {
    throw new Error(`本次最多可选择 ${authorLimit} 位作者，请删减后再继续`);
  }
}

export function validateResearchConfiguration(
  configuration: ResearchConfiguration,
  mode: ResearchType,
  settings: Partial<AppSettings>,
): void {
  const keywordCount = configuration.source.keywords.length;
  const userKeywordCount = (configuration.source.user_keywords ?? []).length;
  const authorCount = normalizeAuthorSourceValues([
    ...configuration.source.profile_urls,
    ...(configuration.source.author_ids ?? []),
  ]).length;
  const invalidAuthors = invalidAuthorSourceValues([
    ...configuration.source.profile_urls,
    ...(configuration.source.author_ids ?? []),
  ]);

  if (mode === 'keyword' && keywordCount === 0 && userKeywordCount === 0) {
    throw new Error('关键词任务请至少开启采集相关帖子或采集相关作者');
  }
  if (mode === 'author' && authorCount === 0) {
    throw new Error('作者采集至少需要一位作者');
  }
  if (mode === 'mixed' && keywordCount === 0 && authorCount === 0 && userKeywordCount === 0) {
    throw new Error('综合调研至少需要一个帖子关键词、用户关键词或一位作者');
  }
  if (invalidAuthors.length > 0) {
    throw new Error('作者来源只能填写小红书作者主页 URL 或不含路径的作者 ID');
  }
  if (mode === 'author' && userKeywordCount > 0) {
    throw new Error('作者采集不支持按关键词搜索用户');
  }
  if (mode === 'author' && !(configuration.author_collection?.scopes ?? ['basic_info', 'posts']).length) {
    throw new Error('请至少选择一项作者采集内容');
  }

  validateSourceCounts(configuration, settings);
  const userDiscovery = configuration.user_limits?.discovery ?? 5;
  const userDiscoveryMaximum = mode === 'keyword'
    ? undefined
    : sourceLimit(settings, 'max_authors_per_task');
  if (userDiscovery < 1) {
    throw new Error('最多发现用户数不能小于 1');
  }
  if (userDiscoveryMaximum !== undefined && userDiscovery > userDiscoveryMaximum) {
    throw new Error(`最多发现用户数需要在 1–${userDiscoveryMaximum} 之间`);
  }
  validateLimits('关键词', configuration.keyword_limits);
  validateLimits('作者', configuration.author_limits, maxAuthorNotes(settings));
}

export function researchValuesFromTask(
  task: Task,
  settings: Partial<AppSettings>,
): ResearchFormValues {
  const defaults = defaultResearchValues(settings);
  const input = task.input_json;
  const source = input.source;
  const sharedLimits = input.limits;
  const keywordLimits = input.keyword_limits ??
    (task.mode === 'author' ? undefined : sharedLimits) ?? {
      discovery: defaults.keywordDiscovery ?? 20,
      deep: defaults.keywordDeep ?? 5,
    };
  const authorLimits = input.author_limits ??
    (task.mode === 'author' ? sharedLimits : undefined) ?? {
      discovery: defaults.authorDiscovery ?? 20,
      deep: defaults.authorDeep ?? 5,
    };
  const authorMaximum = maxAuthorNotes(settings);
  const authorDiscovery = Math.min(authorLimits.discovery, authorMaximum);
  const taskKeywords = source?.keywords ?? [];
  const taskUserKeywords = source?.user_keywords ?? [];
  const keywordInputs = unique([...taskKeywords, ...taskUserKeywords]);

  return {
    ...defaults,
    mode: task.mode === 'post' ? defaults.mode : task.mode,
    topic: input.topic ?? '',
    keywords: task.mode === 'keyword' ? keywordInputs : taskKeywords,
    projectKeywords: [],
    keywordCollectPosts: task.mode !== 'keyword' || taskKeywords.length > 0,
    keywordCollectAuthors:
      task.mode === 'keyword' && taskUserKeywords.length > 0,
    keywordAuthorLimit:
      input.user_limits?.discovery ?? defaults.keywordAuthorLimit ?? 5,
    authors: normalizeAuthorSourceValues([
      ...(source?.profile_urls ?? []),
      ...(source?.author_ids ?? []),
    ]).join('\n'),
    userKeywords: source?.user_keywords ?? [],
    userDiscovery: input.user_limits?.discovery ?? defaults.userDiscovery ?? 5,
    keywordDiscovery: keywordLimits.discovery,
    keywordDeep: keywordLimits.deep,
    authorDiscovery,
    authorDeep: Math.min(authorLimits.deep, authorDiscovery, authorMaximum),
    authorScopes: input.author_collection?.scopes ?? ['basic_info', 'posts'],
    sort: source?.filters.sort ?? '综合',
    publishTime: source?.filters.publish_time ?? '不限',
    forceRefresh: Boolean(input.force_refresh),
  };
}

export function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) return error.message;
  if (typeof error === 'string' && error.trim()) return error;
  return '请求未完成，请检查本地服务状态后重试';
}
