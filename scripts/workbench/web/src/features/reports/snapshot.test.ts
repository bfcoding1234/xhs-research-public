import { describe, expect, it } from 'vitest';
import { reportVisionCoverage } from './snapshot';

describe('report evidence snapshot', () => {
  it('uses the selected historical report snapshot, including zero', () => {
    expect(reportVisionCoverage({ vision_post_count: 7 })).toBe('7');
    expect(reportVisionCoverage({ vision_post_count: 0 })).toBe('0');
  });

  it('shows an em dash when the historical snapshot has no vision count', () => {
    expect(reportVisionCoverage({})).toBe('—');
    expect(reportVisionCoverage({ vision_post_count: null })).toBe('—');
  });
});
