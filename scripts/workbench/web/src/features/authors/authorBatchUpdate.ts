import type { Author, TaskReceipt } from '@/types';

export const MAX_AUTHOR_BATCH_SIZE = 20;

export type BatchAuthor = Pick<Author, 'id' | 'author_id' | 'display_name'>;

export interface AuthorBatchFailure {
  author: BatchAuthor;
  message: string;
}

export interface AuthorBatchSuccess {
  author: BatchAuthor;
  task: TaskReceipt;
}

export interface AuthorBatchResult {
  successes: AuthorBatchSuccess[];
  failures: AuthorBatchFailure[];
}

export async function submitAuthorUpdateBatch(
  authors: BatchAuthor[],
  submitAuthor: (author: BatchAuthor) => Promise<TaskReceipt>,
  onProgress?: (completed: number, total: number) => void,
): Promise<AuthorBatchResult> {
  const result: AuthorBatchResult = { successes: [], failures: [] };

  for (const [index, author] of authors.entries()) {
    try {
      const task = await submitAuthor(author);
      result.successes.push({ author, task });
    } catch (error) {
      result.failures.push({
        author,
        message: error instanceof Error ? error.message : '任务创建失败',
      });
    }
    onProgress?.(index + 1, authors.length);
  }

  return result;
}
