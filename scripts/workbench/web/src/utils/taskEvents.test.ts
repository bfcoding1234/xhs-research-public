import { describe, expect, it } from 'vitest';
import { taskEventWarnings } from './taskEvents';

describe('task event warnings', () => {
  it('normalizes string and structured warnings while dropping empty values', () => {
    expect(
      taskEventWarnings({
        warnings: ['帖子 A 详情失败', { message: '帖子 B 未返回图片' }, { error: '批次超时' }, ''],
      }),
    ).toEqual(['帖子 A 详情失败', '帖子 B 未返回图片', '批次超时']);
  });

  it('returns an empty list when warnings are absent', () => {
    expect(taskEventWarnings({ message: '完成' })).toEqual([]);
  });
});
