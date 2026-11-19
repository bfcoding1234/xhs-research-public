import { describe, expect, it } from 'vitest';
import {
  expectedVisionCount,
  formatPublishDate,
  formatTaskDuration,
  splitValues,
  taskDurationMs,
  taskPercent,
  taskTypeLabels,
} from './format';

describe('format utilities', () => {
  it('uses the user-facing collection label for research tasks', () => {
    expect(taskTypeLabels.research).toBe('采集');
  });

  it('splits Chinese and English separators without empty values', () => {
    expect(splitValues('AI 产品经理，Agent\nRAG,')).toEqual(['AI 产品经理', 'Agent', 'RAG']);
  });

  it('preserves a zero percent vision setting and still honors the minimum', () => {
    expect(
      expectedVisionCount(40, {
        mode: 'vision-selective',
        vision_ratio: 0,
        vision_count: 3,
        vision_max_count: 20,
      }),
    ).toBe(3);
  });

  it('uses every pending post in vision-all mode', () => {
    expect(
      expectedVisionCount(41, {
        mode: 'vision-all',
        vision_ratio: 0.1,
        vision_count: 2,
        vision_max_count: 5,
      }),
    ).toBe(41);
  });

  it('clamps task progress and completes terminal success at 100 percent', () => {
    expect(taskPercent({ status: 'running', progress_current: 12, progress_total: 10 })).toBe(100);
    expect(taskPercent({ status: 'completed', progress_current: 0, progress_total: 0 })).toBe(100);
    expect(taskPercent({ status: 'queued', progress_current: 0, progress_total: 0 })).toBe(4);
  });

  it('calculates task lifecycle duration and formats compact Chinese units', () => {
    expect(taskDurationMs({
      created_at: '2026-08-11T10:00:00Z',
      finished_at: '2026-08-11T10:01:01.500Z',
    })).toBe(61_500);
    expect(taskDurationMs(
      { created_at: '2026-08-11T10:00:00Z', finished_at: null },
      Date.parse('2026-08-11T11:02:00Z'),
    )).toBe(3_720_000);
    expect(formatTaskDuration(500)).toBe('< 1 秒');
    expect(formatTaskDuration(61_500)).toBe('1 分 1 秒');
    expect(formatTaskDuration(3_720_000)).toBe('1 小时 2 分');
    expect(formatTaskDuration(93_600_000)).toBe('1 天 2 小时');
    expect(formatTaskDuration(null)).toBe('—');
  });

  it('formats precise post timestamps in Shanghai time without inventing time for date-only values', () => {
    expect(formatPublishDate('2026-07-31T06:23:10+00:00')).toBe('2026-07-31 14:23');
    expect(formatPublishDate('2026-07-31T06:23:10+08:00')).toBe('2026-07-31 06:23');
    expect(formatPublishDate('2026-07-31')).toBe('2026-07-31');
    expect(formatPublishDate('')).toBe('—');
    expect(formatPublishDate('unknown')).toBe('unknown');
  });
});
