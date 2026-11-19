import type { Report, ReportStatus } from '@/types';

export interface ReportCoverageComparison {
  current: {
    posts: number;
    authors: number;
    ocrPosts: number;
    visionPosts: number;
  };
  snapshot: {
    posts: number;
    authors: number;
    ocrPosts: number | null;
    visionPosts: number | null;
  };
}

function finiteNumber(value: unknown): number | null {
  const number = Number(value);
  return value === null || value === undefined || value === '' || !Number.isFinite(number)
    ? null
    : number;
}

export function reportDisplayVersion(
  report: Pick<Report, 'generator_version' | 'version'>,
): number {
  return finiteNumber(report.generator_version) ?? report.version;
}

export function reportCoverageComparison(
  report: Pick<Report, 'evidence_post_count' | 'evidence_author_count' | 'evidence_snapshot_json'>,
  status: ReportStatus,
): ReportCoverageComparison {
  const snapshot = report.evidence_snapshot_json;
  return {
    current: {
      posts: status.post_count,
      authors: status.author_count,
      ocrPosts: status.ocr_post_count,
      visionPosts: status.vision_post_count,
    },
    snapshot: {
      posts: finiteNumber(snapshot.post_count) ?? report.evidence_post_count,
      authors: finiteNumber(snapshot.author_count) ?? report.evidence_author_count,
      ocrPosts: finiteNumber(snapshot.ocr_post_count),
      visionPosts: finiteNumber(snapshot.vision_post_count),
    },
  };
}
