import { describe, expect, it } from 'vitest';
import type { Report, ReportStatus } from '@/types';
import { reportCoverageComparison, reportDisplayVersion } from './presentation';

const report: Pick<
  Report,
  | 'version'
  | 'generator_version'
  | 'evidence_post_count'
  | 'evidence_author_count'
  | 'evidence_snapshot_json'
> = {
  version: 3,
  generator_version: 2,
  evidence_post_count: 23,
  evidence_author_count: 1,
  evidence_snapshot_json: {
    post_count: 23,
    author_count: 1,
    ocr_post_count: 23,
    vision_post_count: 0,
  },
};

const status: ReportStatus = {
  provider_available: true,
  post_count: 23,
  author_count: 1,
  ocr_post_count: 23,
  vision_post_count: 23,
};

describe('report presentation contract', () => {
  it('uses generator-scoped versions', () => {
    expect(reportDisplayVersion(report)).toBe(2);
  });

  it('keeps current coverage distinct from the historical evidence snapshot', () => {
    expect(reportCoverageComparison(report, status)).toEqual({
      current: { posts: 23, authors: 1, ocrPosts: 23, visionPosts: 23 },
      snapshot: { posts: 23, authors: 1, ocrPosts: 23, visionPosts: 0 },
    });
  });
});
