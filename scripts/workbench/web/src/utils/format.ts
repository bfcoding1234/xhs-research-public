import type { ResearchType, Task, TaskStatus, TaskType } from '@/types';

export const researchTypeLabels: Record<ResearchType, string> = {
  keyword: '关键词调研',
  author: '作者调研',
  mixed: '综合调研',
};

export const taskTypeLabels: Record<TaskType, string> = {
  research: '采集',
  vision: '图片理解',
  ai_report: '大模型报告',
  keyword_suggestions: 'AI 关键词生成',
  comments: '评论采集',
};

export const taskStatusLabels: Record<TaskStatus, string> = {
  queued: '排队中',
  running: '运行中',
  waiting_login: '等待人工验证',
  completed: '已完成',
  partial: '部分完成',
  failed: '失败',
  cancelled: '已取消',
};

export const taskPhaseLabels: Record<string, string> = {
  starting: '准备任务',
  preparing_vision: '准备图片',
  discovery: '发现帖子',
  deep_scan: '深度读取',
  vision: '图片理解',
  report_generation: '生成大模型报告',
  keyword_generation: '生成候选关键词',
  collecting_comments: '采集评论',
  login_verified: '登录态已校验',
  completed: '已完成',
  failed: '失败',
  waiting_login: '等待人工验证',
};

export const activeTaskStatuses = new Set<TaskStatus>([
  'queued',
  'running',
  'waiting_login',
]);

export function formatNumber(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString('zh-CN') : String(value);
}

export function formatBytes(value: unknown): string {
  const size = Number(value || 0);
  if (size < 1024) return `${size} B`;
  if (size < 1024 ** 2) return `${(size / 1024).toFixed(1)} KB`;
  if (size < 1024 ** 3) return `${(size / 1024 ** 2).toFixed(1)} MB`;
  return `${(size / 1024 ** 3).toFixed(1)} GB`;
}

export function formatDate(value?: string | null, includeSeconds = false): string {
  if (!value) return '—';
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: includeSeconds ? '2-digit' : undefined,
    hourCycle: 'h23',
  }).format(date);
}

export function taskDurationMs(
  task: Pick<Task, 'created_at' | 'finished_at'>,
  now = Date.now(),
): number | null {
  const startedAt = Date.parse(task.created_at);
  const finishedAt = task.finished_at ? Date.parse(task.finished_at) : now;
  if (!Number.isFinite(startedAt) || !Number.isFinite(finishedAt)) return null;
  return Math.max(0, finishedAt - startedAt);
}

export function formatTaskDuration(milliseconds: number | null): string {
  if (milliseconds === null || !Number.isFinite(milliseconds)) return '—';
  const totalSeconds = Math.floor(Math.max(0, milliseconds) / 1_000);
  if (totalSeconds < 1) return '< 1 秒';
  if (totalSeconds < 60) return `${totalSeconds} 秒`;
  const totalMinutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (totalMinutes < 60) return `${totalMinutes} 分${seconds ? ` ${seconds} 秒` : ''}`;
  const totalHours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (totalHours < 24) return `${totalHours} 小时${minutes ? ` ${minutes} 分` : ''}`;
  const days = Math.floor(totalHours / 24);
  const hours = totalHours % 24;
  return `${days} 天${hours ? ` ${hours} 小时` : ''}`;
}

export function formatPublishDate(value?: string | null): string {
  const text = String(value || '').trim();
  if (!text) return '—';
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return text;

  const isoLike = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(text)
    ? text.replace(' ', 'T')
    : text;
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(isoLike) ? isoLike : `${isoLike}Z`;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return text;

  const parts = new Map(
    new Intl.DateTimeFormat('zh-CN', {
      timeZone: 'Asia/Shanghai',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    })
      .formatToParts(date)
      .map((part) => [part.type, part.value]),
  );
  return `${parts.get('year')}-${parts.get('month')}-${parts.get('day')} ${parts.get('hour')}:${parts.get('minute')}`;
}

export function taskPercent(task?: Pick<Task, 'status' | 'progress_current' | 'progress_total'>): number {
  if (!task) return 0;
  if (task.status === 'completed') return 100;
  if (!task.progress_total) return activeTaskStatuses.has(task.status) ? 4 : 0;
  return Math.max(
    0,
    Math.min(100, Math.round((task.progress_current / task.progress_total) * 100)),
  );
}

export function splitValues(value: unknown): string[] {
  return String(value || '')
    .split(/[\n,，]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function expectedVisionCount(
  pending: number,
  configuration: {
    mode: string;
    vision_ratio: number;
    vision_count: number;
    vision_max_count: number;
  },
): number {
  if (configuration.mode === 'vision-all') return pending;
  const ratioCount = Math.ceil(pending * configuration.vision_ratio);
  return Math.min(pending, configuration.vision_max_count, Math.max(configuration.vision_count, ratioCount));
}
