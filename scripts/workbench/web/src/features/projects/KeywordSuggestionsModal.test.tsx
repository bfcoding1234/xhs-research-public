import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { App as AntApp } from 'antd';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiService } from '@/services/api';
import type { ProjectKeyword } from '@/types';
import KeywordSuggestionsModal from './KeywordSuggestionsModal';

const manualKeyword: ProjectKeyword = {
  id: 1,
  project_id: 12,
  keyword: 'AI 产品经理',
  source: 'manual',
  created_at: '',
  updated_at: '',
};

function renderModal(
  projectKeywords: ProjectKeyword[] = [manualKeyword],
  onAdd = vi.fn().mockResolvedValue(projectKeywords),
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AntApp>
        <KeywordSuggestionsModal
          project={{ id: 12, name: 'AI 产品经理内容机会', description: '研究工作方式变化' }}
          projectKeywords={projectKeywords}
          open
          onClose={vi.fn()}
          onAdd={onAdd}
          onAdded={vi.fn()}
        />
      </AntApp>
    </QueryClientProvider>,
  );
}

describe('KeywordSuggestionsModal', () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
    vi.spyOn(apiService, 'projectTasks').mockResolvedValue([]);
  });

  it('defaults to manual keywords and allows generating from project information only', () => {
    renderModal();

    expect(screen.getByRole('checkbox', { name: /手工关键词/ })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /AI 生成关键词/ })).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox', { name: /手工关键词/ }));
    expect(screen.getByRole('checkbox', { name: /手工关键词/ })).not.toBeChecked();
  });

  it('keeps successful candidates in session storage with no default selection', async () => {
    vi.spyOn(apiService, 'createProjectKeywordSuggestions').mockResolvedValue({
      id: 'task-keyword-1', status: 'queued', url: '/#/tasks/task-keyword-1',
    });
    vi.spyOn(apiService, 'task').mockResolvedValue({
      id: 'task-keyword-1', project_id: 12, author_id: null, task_type: 'keyword_suggestions',
      mode: 'keyword', created_from: 'web', input_json: {}, status: 'completed',
      current_phase: 'completed', progress_current: 1, progress_total: 1, warning_count: 0,
      error_message: '', result_json: {
        keyword_suggestions: {
          request_id: 'task-keyword-1',
          keywords: [{ keyword: 'AI 需求分析', category: '使用场景', reason: '覆盖需求工作' }],
          reference_sources: ['manual'],
        },
      }, created_at: '', started_at: '', finished_at: '',
    });
    renderModal();

    fireEvent.click(screen.getByRole('button', { name: /生成候选关键词/ }));
    expect(await screen.findByText('AI 需求分析')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: '选择关键词：AI 需求分析' })).not.toBeChecked();
    expect(
      JSON.parse(
        sessionStorage.getItem('xhs-research:keyword-suggestions:12') ?? '{}',
      ),
    ).toMatchObject({
      selectedKeywords: [],
      referenceSources: ['manual'],
    });
    expect(sessionStorage.getItem('xhs-research:keyword-suggestion-task:12')).toBeNull();
  });

  it('marks a cached candidate as added using the latest project keywords', async () => {
    sessionStorage.setItem(
      'xhs-research:keyword-suggestions:12',
      JSON.stringify({
        version: 1,
        keywords: [
          { keyword: 'AI 需求分析', category: '使用场景', reason: '覆盖需求工作' },
        ],
        referenceSources: ['manual'],
        selectedKeywords: ['AI 需求分析'],
        generatedAt: '2026-07-31T10:00:00Z',
      }),
    );

    renderModal([
      manualKeyword,
      { ...manualKeyword, id: 2, keyword: 'AI 需求分析', source: 'ai_generated' },
    ]);

    expect(await screen.findByText('已添加')).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole('checkbox', { name: '选择关键词：AI 需求分析' })).toBeDisabled(),
    );
  });

  it('blocks reference changes and regeneration while selected keywords are being added', async () => {
    sessionStorage.setItem(
      'xhs-research:keyword-suggestions:12',
      JSON.stringify({
        version: 1,
        keywords: [
          { keyword: 'AI 需求分析', category: '使用场景', reason: '覆盖需求工作' },
        ],
        referenceSources: ['manual'],
        selectedKeywords: ['AI 需求分析'],
        generatedAt: '2026-07-31T10:00:00Z',
      }),
    );
    const pendingAdd = vi.fn(() => new Promise<ProjectKeyword[]>(() => undefined));
    renderModal([manualKeyword], pendingAdd);

    fireEvent.click(await screen.findByRole('button', { name: /添加所选 1 个/ }));

    expect(screen.getByRole('button', { name: '调整参考来源' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '重新生成' })).toBeDisabled();
    expect(pendingAdd).toHaveBeenCalledWith(['AI 需求分析'], 'ai_generated');
  });
});
