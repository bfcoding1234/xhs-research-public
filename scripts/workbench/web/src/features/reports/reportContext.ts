import type {
  JsonObject,
  ReportContextConfiguration,
  ReportContextDetail,
  ReportPostSection,
  ReportPostSelectionMode,
} from '@/types';

export const reportContextOptions: Array<{
  value: ReportContextDetail;
  label: string;
  description: string;
}> = [
  {
    value: 'brief',
    label: '概览',
    description: '核心统计与代表帖子，适合快速判断方向。',
  },
  {
    value: 'standard',
    label: '标准',
    description: '代表帖子、作者、OCR 与图片理解摘要，适合常规调研。',
  },
  {
    value: 'detailed',
    label: '深入',
    description: '更多帖子及更完整的正文、OCR 与图片理解信息。',
  },
];

export function reportContextLabel(value: unknown): string {
  return reportContextOptions.find((option) => option.value === value)?.label ?? '标准';
}

export const defaultReportContextConfiguration: ReportContextConfiguration = {
  authors: { enabled: true },
  posts: {
    enabled: true,
    selection_mode: 'representative',
    sections: ['basic', 'content', 'ocr'],
  },
};

export const reportPostSectionLabels: Record<ReportPostSection, string> = {
  basic: '基础信息',
  content: '正文',
  ocr: 'OCR 文本',
  vision: '大模型理解文本',
};

export const reportPostSelectionLabels: Record<ReportPostSelectionMode, string> = {
  representative: '有代表性的帖子',
  expanded: '更多帖子',
  all: '全部帖子',
};

export function reportPostSelectionCount(total: number, mode: ReportPostSelectionMode): number {
  const safeTotal = Math.max(0, Math.floor(total));
  if (!safeTotal) return 0;
  if (mode === 'all') return safeTotal;
  const count = Math.max(1, Math.ceil(safeTotal * (mode === 'representative' ? 0.2 : 0.5)));
  return mode === 'representative' ? Math.min(20, count) : Math.min(safeTotal, count);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

export function reportContextSummary(configuration: JsonObject | Record<string, unknown>): string {
  const configuredSources = Array.isArray(configuration.sources)
    ? configuration.sources.map(String)
    : undefined;
  const context = isRecord(configuration.context_config) ? configuration.context_config : undefined;
  const authors = context && isRecord(context.authors) ? context.authors : undefined;
  const posts = context && isRecord(context.posts) ? context.posts : undefined;
  if (!configuredSources && (!context || !authors || !posts)) {
    return reportContextLabel(configuration.context_detail);
  }
  const sources: string[] = [];
  if (configuredSources?.includes('data_summary')) {
    const summary = isRecord(configuration.data_summary) ? configuration.data_summary : undefined;
    sources.push(`数据摘要${summary?.version ? ` v${summary.version}` : ''}`);
  }
  const detailParts: string[] = [];
  if (authors?.enabled === true) detailParts.push('作者');
  if (posts?.enabled === true) {
    const mode = String(posts.selection_mode || 'representative') as ReportPostSelectionMode;
    const ratio = mode === 'representative' ? '20%，最多 20 篇' : mode === 'expanded' ? '50%' : '100%';
    const sections = Array.isArray(posts.sections)
      ? posts.sections
        .filter((section): section is ReportPostSection => section in reportPostSectionLabels)
        .map((section) => reportPostSectionLabels[section])
      : [];
    detailParts.push(`帖子（${ratio}${sections.length ? `；${sections.join('、')}` : ''}）`);
  }
  if (configuredSources?.includes('current_detail') || (!configuredSources && detailParts.length)) {
    sources.push(`当前明细：${detailParts.join(' + ') || '未设置'}`);
  }
  return sources.join(' + ') || '未设置';
}
