import { describe, expect, it, vi } from 'vitest';
import type { TaskReceipt } from '@/types';
import { submitAuthorUpdateBatch } from './authorBatchUpdate';

const authors = [
  { id: 1, author_id: 'author-a', display_name: '作者甲' },
  { id: 2, author_id: 'author-b', display_name: '作者乙' },
  { id: 3, author_id: 'author-c', display_name: '作者丙' },
];

function receipt(id: string): TaskReceipt {
  return { id, status: 'queued', url: `/tasks/${id}` };
}

describe('submitAuthorUpdateBatch', () => {
  it('submits authors sequentially and reports progress', async () => {
    const order: string[] = [];
    const progress = vi.fn();
    const result = await submitAuthorUpdateBatch(
      authors,
      async (author) => {
        order.push(`start:${author.author_id}`);
        await Promise.resolve();
        order.push(`end:${author.author_id}`);
        return receipt(`task-${author.id}`);
      },
      progress,
    );

    expect(order).toEqual([
      'start:author-a',
      'end:author-a',
      'start:author-b',
      'end:author-b',
      'start:author-c',
      'end:author-c',
    ]);
    expect(result.successes).toHaveLength(3);
    expect(result.failures).toEqual([]);
    expect(progress).toHaveBeenLastCalledWith(3, 3);
  });

  it('continues after an author fails and keeps the failure reason', async () => {
    const submit = vi.fn(async (author: (typeof authors)[number]) => {
      if (author.id === 2) throw new Error('作者乙请求失败');
      return receipt(`task-${author.id}`);
    });

    const result = await submitAuthorUpdateBatch(authors, submit);

    expect(submit).toHaveBeenCalledTimes(3);
    expect(result.successes.map(({ author }) => author.id)).toEqual([1, 3]);
    expect(result.failures).toEqual([{ author: authors[1], message: '作者乙请求失败' }]);
  });
});
