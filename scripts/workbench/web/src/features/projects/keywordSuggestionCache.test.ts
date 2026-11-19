import { beforeEach, describe, expect, it } from 'vitest';
import type { KeywordSuggestionsResponse } from '@/types';
import {
  clearKeywordSuggestionCache,
  createKeywordSuggestionCache,
  loadKeywordSuggestionCache,
  saveKeywordSuggestionCache,
} from './keywordSuggestionCache';

const response: KeywordSuggestionsResponse = {
  request_id: 'request-1',
  keywords: [
    { keyword: 'AI 工作流', category: '工作场景', reason: '覆盖日常工作实践' },
    { keyword: 'AI 工作流 ', category: '重复', reason: '应被去重' },
    { keyword: '产品经理转型', category: '职业发展', reason: '覆盖职业变化' },
  ],
  reference_sources: ['manual'],
  model: 'codex',
  prompt_version: 'v1',
};

describe('keywordSuggestionCache', () => {
  beforeEach(() => sessionStorage.clear());

  it('stores candidates by project and restores their selection state', () => {
    const cache = createKeywordSuggestionCache(response, '2026-07-31T10:00:00Z');
    const selected = { ...cache, selectedKeywords: ['AI 工作流'] };
    saveKeywordSuggestionCache(12, selected);

    expect(loadKeywordSuggestionCache(12)).toEqual(selected);
    expect(loadKeywordSuggestionCache(13)).toBeUndefined();
  });

  it('deduplicates and limits candidates before caching', () => {
    const cache = createKeywordSuggestionCache({
      ...response,
      keywords: [
        ...response.keywords,
        ...Array.from({ length: 20 }, (_, index) => ({
          keyword: `候选 ${index}`,
          category: '扩展',
          reason: '测试候选上限',
        })),
      ],
    });

    expect(cache.keywords).toHaveLength(12);
    expect(cache.keywords.filter((item) => item.keyword === 'AI 工作流')).toHaveLength(1);
    expect(cache.selectedKeywords).toEqual([]);
  });

  it('ignores malformed session data', () => {
    sessionStorage.setItem('xhs-research:keyword-suggestions:12', '{"version":1,"keywords":"bad"}');
    expect(loadKeywordSuggestionCache(12)).toBeUndefined();
  });

  it('clears only the deleted project cache', () => {
    const cache = createKeywordSuggestionCache(response);
    saveKeywordSuggestionCache(12, cache);
    saveKeywordSuggestionCache(13, cache);

    clearKeywordSuggestionCache(12);

    expect(loadKeywordSuggestionCache(12)).toBeUndefined();
    expect(loadKeywordSuggestionCache(13)).toEqual(cache);
  });
});
