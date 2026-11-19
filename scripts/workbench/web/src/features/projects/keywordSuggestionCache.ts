import type {
  KeywordSuggestion,
  KeywordSuggestionsResponse,
  ProjectKeywordSource,
} from '@/types';

const CACHE_PREFIX = 'xhs-research:keyword-suggestions:';
const CACHE_VERSION = 1;
const MAX_SUGGESTIONS = 12;

export interface KeywordSuggestionCache {
  version: typeof CACHE_VERSION;
  keywords: KeywordSuggestion[];
  referenceSources: ProjectKeywordSource[];
  selectedKeywords: string[];
  generatedAt: string;
  model?: string;
  promptVersion?: string;
}

export function normalizeKeyword(value: string): string {
  return value.trim().toLocaleLowerCase();
}

function storageKey(projectId: number | string): string {
  return `${CACHE_PREFIX}${projectId}`;
}

function availableSessionStorage(): Storage | undefined {
  try {
    return typeof window === 'undefined' ? undefined : window.sessionStorage;
  } catch {
    return undefined;
  }
}

function validSource(value: unknown): value is ProjectKeywordSource {
  return value === 'manual' || value === 'ai_generated';
}

function validSuggestion(value: unknown): value is KeywordSuggestion {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Partial<KeywordSuggestion>;
  return (
    typeof candidate.keyword === 'string' &&
    Boolean(candidate.keyword.trim()) &&
    typeof candidate.category === 'string' &&
    typeof candidate.reason === 'string'
  );
}

export function createKeywordSuggestionCache(
  response: KeywordSuggestionsResponse,
  generatedAt = new Date().toISOString(),
): KeywordSuggestionCache {
  const seen = new Set<string>();
  const keywords = response.keywords
    .filter(validSuggestion)
    .filter((candidate) => {
      const normalized = normalizeKeyword(candidate.keyword);
      if (!normalized || seen.has(normalized)) return false;
      seen.add(normalized);
      return true;
    })
    .slice(0, MAX_SUGGESTIONS)
    .map((candidate) => ({
      keyword: candidate.keyword.trim(),
      category: candidate.category.trim(),
      reason: candidate.reason.trim(),
    }));

  return {
    version: CACHE_VERSION,
    keywords,
    referenceSources: [...new Set(response.reference_sources.filter(validSource))],
    selectedKeywords: [],
    generatedAt,
    model: response.model,
    promptVersion: response.prompt_version,
  };
}

export function loadKeywordSuggestionCache(
  projectId: number | string,
  storage = availableSessionStorage(),
): KeywordSuggestionCache | undefined {
  if (!storage) return undefined;
  try {
    const raw = storage.getItem(storageKey(projectId));
    if (!raw) return undefined;
    const parsed = JSON.parse(raw) as Partial<KeywordSuggestionCache>;
    if (
      parsed.version !== CACHE_VERSION ||
      !Array.isArray(parsed.keywords) ||
      !Array.isArray(parsed.referenceSources) ||
      !Array.isArray(parsed.selectedKeywords) ||
      typeof parsed.generatedAt !== 'string'
    ) {
      return undefined;
    }
    const keywords = parsed.keywords.filter(validSuggestion).slice(0, MAX_SUGGESTIONS);
    if (!keywords.length && parsed.keywords.length) return undefined;
    const available = new Set(keywords.map((candidate) => normalizeKeyword(candidate.keyword)));
    return {
      version: CACHE_VERSION,
      keywords,
      referenceSources: parsed.referenceSources.filter(validSource),
      selectedKeywords: parsed.selectedKeywords.filter(
        (keyword): keyword is string =>
          typeof keyword === 'string' && available.has(normalizeKeyword(keyword)),
      ),
      generatedAt: parsed.generatedAt,
      model: typeof parsed.model === 'string' ? parsed.model : undefined,
      promptVersion:
        typeof parsed.promptVersion === 'string' ? parsed.promptVersion : undefined,
    };
  } catch {
    return undefined;
  }
}

export function saveKeywordSuggestionCache(
  projectId: number | string,
  cache: KeywordSuggestionCache,
  storage = availableSessionStorage(),
): void {
  if (!storage) return;
  try {
    storage.setItem(storageKey(projectId), JSON.stringify(cache));
  } catch {
    // sessionStorage may be unavailable or full; generation remains usable in memory.
  }
}

export function clearKeywordSuggestionCache(
  projectId: number | string,
  storage = availableSessionStorage(),
): void {
  if (!storage) return;
  try {
    storage.removeItem(storageKey(projectId));
  } catch {
    // Project deletion remains successful even when browser storage is unavailable.
  }
}
