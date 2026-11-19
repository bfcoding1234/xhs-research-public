const TASK_PREFIX = 'xhs-research:keyword-suggestion-task:';

function storageKey(projectId: number | string): string {
  return `${TASK_PREFIX}${projectId}`;
}

function storage(): Storage | undefined {
  try {
    return typeof window === 'undefined' ? undefined : window.sessionStorage;
  } catch {
    return undefined;
  }
}

export function loadKeywordSuggestionTask(projectId: number | string): string | undefined {
  const value = storage()?.getItem(storageKey(projectId))?.trim();
  return value || undefined;
}

export function saveKeywordSuggestionTask(projectId: number | string, taskId: string): void {
  storage()?.setItem(storageKey(projectId), taskId);
}

export function clearKeywordSuggestionTask(projectId: number | string): void {
  storage()?.removeItem(storageKey(projectId));
}
