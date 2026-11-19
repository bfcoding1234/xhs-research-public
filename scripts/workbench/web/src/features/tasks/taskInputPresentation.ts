import type { Task } from '@/types';
import { researchTypeLabels } from '@/utils/format';
import { reportContextSummary } from '@/features/reports/reportContext';

export interface TaskInputPresentationItem {
  key: string;
  label: string;
  value: string;
}

export interface TaskInputPresentationSection {
  key: string;
  title: string;
  items: TaskInputPresentationItem[];
}

export interface TaskInputPresentation {
  sections: TaskInputPresentationSection[];
  rawJson: string;
}

const authorUpdateScopeLabels: Record<string, string> = {
  basic_info: '基础信息',
  preview_posts: '预览帖子',
  detailed_posts: '详细帖子',
};

const authorUpdateTargetLabels: Record<string, string> = {
  basic_unupdated: '基础信息未更新的作者',
  posts_unupdated: '帖子信息未更新的作者',
  all: '当前项目全部作者',
};

const postDetailTargetLabels: Record<string, string> = {
  selected: '选中的帖子',
  needs_update: '需要补全或详情已过期的帖子',
  preview: '仅有预览信息的帖子',
  all: '当前范围全部帖子',
};

const postDetailScopeLabels: Record<string, string> = {
  global: '全部帖子主数据',
  project: '当前项目',
  author: '当前作者',
};

const visionModeLabels: Record<string, string> = {
  'vision-selective': '选择性分析未处理图片',
  'vision-all': '优先分析全部未处理图片',
  'ocr-only': '仅 OCR',
};

const imageScopeLabels: Record<string, string> = {
  cover: '封面图',
  detail: '详情图片',
  all: '全部图片（历史默认）',
};

const presentationPageModeLabels: Record<string, string> = {
  concise: '精简（6～8 页）',
  standard: '标准（9～12 页）',
  complete: '完整（13～16 页）',
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function text(value: unknown): string | undefined {
  if (typeof value === 'string') {
    const normalized = value.trim();
    return normalized || undefined;
  }
  if (typeof value === 'number' && Number.isFinite(value)) return value.toLocaleString('zh-CN');
  if (typeof value === 'boolean') return value ? '是' : '否';
  return undefined;
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => text(item))
    .filter((item): item is string => Boolean(item));
}

function listText(value: unknown): string | undefined {
  const values = stringList(value);
  return values.length ? values.join('、') : undefined;
}

function numberValue(value: unknown): number | undefined {
  const next = Number(value);
  return Number.isFinite(next) ? next : undefined;
}

function percentText(value: unknown): string | undefined {
  const number = numberValue(value);
  if (number === undefined) return undefined;
  return `${Math.round(number * 100)}%`;
}

function limitsText(value: unknown): string | undefined {
  if (!isRecord(value)) return undefined;
  const discovery = numberValue(value.discovery);
  const deep = numberValue(value.deep);
  if (discovery === undefined && deep === undefined) return undefined;
  return `${discovery?.toLocaleString('zh-CN') ?? '—'} / ${deep?.toLocaleString('zh-CN') ?? '—'}`;
}

function item(key: string, label: string, value: unknown): TaskInputPresentationItem | undefined {
  const displayValue = text(value);
  return displayValue ? { key, label, value: displayValue } : undefined;
}

function compact<T>(items: Array<T | undefined>): T[] {
  return items.filter((entry): entry is T => Boolean(entry));
}

function section(
  key: string,
  title: string,
  items: Array<TaskInputPresentationItem | undefined>,
): TaskInputPresentationSection | undefined {
  const nextItems = compact(items);
  return nextItems.length ? { key, title, items: nextItems } : undefined;
}

function researchSections(task: Task): TaskInputPresentationSection[] {
  const input = task.input_json;
  if (input.operation === 'project_author_update') {
    return projectAuthorUpdateSections(task);
  }
  if (input.operation === 'post_detail_update') {
    return postDetailUpdateSections(task);
  }
  const source: Record<string, unknown> = isRecord(input.source) ? input.source : {};
  const filters: Record<string, unknown> = isRecord(source.filters) ? source.filters : {};
  const userLimits: Record<string, unknown> = isRecord(input.user_limits) ? input.user_limits : {};
  const authorUpdate: Record<string, unknown> = isRecord(input.author_update)
    ? input.author_update
    : {};
  const authorScopes = stringList(authorUpdate.scopes)
    .map((scope) => authorUpdateScopeLabels[scope] ?? scope)
    .join('、');

  return compact([
    section('basic', '基本信息', [
      item('mode', '采集类型', task.mode === 'post' ? '单条帖子' : researchTypeLabels[task.mode]),
      item('topic', '采集主题', input.topic),
      item('forceRefresh', '强制刷新', input.force_refresh),
      item('authorUpdateScopes', '更新范围', authorScopes),
    ]),
    section('source', '数据来源', [
      item('keywords', '关键词', listText(source.keywords)),
      item('profileUrls', '作者主页', listText(source.profile_urls)),
      item('authorIds', '作者 ID', listText(source.author_ids)),
      item('userKeywords', '用户关键词', listText(source.user_keywords)),
      item('sort', '排序', filters.sort),
      item('publishTime', '发布时间', filters.publish_time),
    ]),
    section('limits', '数量与规则', [
      item('limits', '执行数量（发现 / 深度）', limitsText(input.limits)),
      item('keywordLimits', '关键词数量（发现 / 深度）', limitsText(input.keyword_limits)),
      item('authorLimits', '作者数量（发现 / 深度）', limitsText(input.author_limits)),
      item('userDiscovery', '用户发现上限', userLimits.discovery),
    ]),
  ]);
}

function postDetailUpdateSections(task: Task): TaskInputPresentationSection[] {
  const input = task.input_json;
  const bulk: Record<string, unknown> = isRecord(input.post_detail_update)
    ? input.post_detail_update
    : {};
  const scope = text(bulk.scope);
  const target = text(bulk.target);
  const postCount = Array.isArray(bulk.post_ids) ? bulk.post_ids.length : undefined;

  return compact([
    section('post-detail-basic', '帖子详情更新范围', [
      item('mode', '执行方式', bulk.mode === 'selected' ? '更新选中帖子' : '批量更新'),
      item('scope', '业务范围', scope ? postDetailScopeLabels[scope] ?? scope : undefined),
      item('target', '目标帖子', target ? postDetailTargetLabels[target] ?? target : undefined),
      item('postCount', '本次帖子数', postCount),
    ]),
    section('post-detail-safety', '安全执行', [
      item('batchSize', '批次大小', bulk.batch_size),
      item('maxPosts', '最大处理帖子数', bulk.max_posts),
      item(
        'postDelay',
        '帖子间隔',
        `${text(bulk.post_delay_min_seconds) ?? '0'}～${text(bulk.post_delay_max_seconds) ?? '0'} 秒`,
      ),
      item(
        'batchDelay',
        '批次间隔',
        `${text(bulk.batch_delay_min_seconds) ?? '0'}～${text(bulk.batch_delay_max_seconds) ?? '0'} 秒`,
      ),
      item('failureLimit', '连续失败阈值', bulk.consecutive_failure_limit),
    ]),
  ]);
}

function projectAuthorUpdateSections(task: Task): TaskInputPresentationSection[] {
  const input = task.input_json;
  const bulk: Record<string, unknown> = isRecord(input.author_update_bulk)
    ? input.author_update_bulk
    : {};
  const scopes = stringList(bulk.scopes)
    .map((scope) => authorUpdateScopeLabels[scope] ?? scope)
    .join('、');
  const authorCount = Array.isArray(bulk.author_ids) ? bulk.author_ids.length : undefined;
  const target = text(bulk.target);

  return compact([
    section('bulk-basic', '批量更新范围', [
      item('target', '目标作者', target ? authorUpdateTargetLabels[target] ?? target : undefined),
      item('authorCount', '本次作者数', authorCount),
      item('scopes', '更新内容', scopes),
      item('previewLimit', '每位作者帖子基础信息数', bulk.preview_limit),
      item('detailLimit', '每位作者帖子详细信息数', bulk.detail_limit),
    ]),
    section('bulk-safety', '安全执行', [
      item('batchSize', '批次大小', bulk.batch_size),
      item('maxAuthors', '最大处理作者数', bulk.max_authors),
      item(
        'authorDelay',
        '作者间隔',
        `${text(bulk.author_delay_min_seconds) ?? '0'}～${text(bulk.author_delay_max_seconds) ?? '0'} 秒`,
      ),
      item(
        'batchDelay',
        '批次间隔',
        `${text(bulk.batch_delay_min_seconds) ?? '0'}～${text(bulk.batch_delay_max_seconds) ?? '0'} 秒`,
      ),
      item('failureLimit', '连续失败阈值', bulk.consecutive_failure_limit),
    ]),
  ]);
}

function visionSections(task: Task): TaskInputPresentationSection[] {
  const input = task.input_json;
  const imageAnalysis: Record<string, unknown> = isRecord(input.image_analysis)
    ? input.image_analysis
    : {};
  const mode = text(imageAnalysis.mode);
  const imageScopes = stringList(imageAnalysis.image_scopes);
  const imageScopeText = (imageScopes.length ? imageScopes : ['all'])
    .map((scope) => imageScopeLabels[scope] ?? scope)
    .join('、');

  return compact([
    section('vision', '图片理解参数', [
      item('scope', '处理范围', input.vision_scope === 'author' || task.author_id ? '当前作者' : '当前项目'),
      item('processingMethod', '补充方式', imageAnalysis.processing_method === 'ocr' ? 'OCR 识图（RapidOCR）' : '大模型理解'),
      item('imageScopes', '图片范围', imageScopeText),
      item('mode', '帖子选择', mode ? visionModeLabels[mode] ?? mode : undefined),
      item('onlyUnanalyzed', '仅处理未分析内容', imageAnalysis.only_unanalyzed),
      item('ratio', '选择比例', percentText(imageAnalysis.vision_ratio)),
      item('count', '最低数量', imageAnalysis.vision_count),
      item('maxCount', '最高数量', imageAnalysis.vision_max_count),
      item('batchSize', '每批帖子数', imageAnalysis.vision_batch_size),
    ]),
  ]);
}

function reportSections(task: Task): TaskInputPresentationSection[] {
  const input = task.input_json;
  if (input.operation === 'html_presentation') {
    const presentation: Record<string, unknown> = isRecord(input.presentation_generation)
      ? input.presentation_generation
      : {};
    const source: Record<string, unknown> = isRecord(presentation.source_report)
      ? presentation.source_report
      : {};
    const pageMode = text(presentation.page_mode);
    return compact([
      section('presentation', 'HTML 演示稿参数', [
        item('scope', '报告范围', input.report_scope === 'author' || task.author_id ? '作者' : '项目'),
        item('sourceReport', '源文字报告', source.title),
        item('sourceVersion', '源报告版本', source.version),
        item('title', '演示稿标题', presentation.title),
        item(
          'pageMode',
          '篇幅',
          pageMode ? presentationPageModeLabels[pageMode] ?? pageMode : undefined,
        ),
        item('instructions', '补充要求', presentation.instructions),
      ]),
    ]);
  }
  const reportGeneration: Record<string, unknown> = isRecord(input.report_generation)
    ? input.report_generation
    : {};

  return compact([
    section('report', '报告参数', [
      item('scope', '报告范围', input.report_scope === 'author' || task.author_id ? '作者' : '项目'),
      item('title', '报告标题', reportGeneration.title),
      item('instructions', '补充要求', reportGeneration.instructions),
      item('contextDetail', '输入上下文', reportContextSummary(reportGeneration)),
    ]),
  ]);
}

function keywordSuggestionSections(task: Task): TaskInputPresentationSection[] {
  const input = task.input_json;
  const configuration: Record<string, unknown> = isRecord(input.keyword_suggestions)
    ? input.keyword_suggestions
    : {};
  const project: Record<string, unknown> = isRecord(configuration.project)
    ? configuration.project
    : {};
  return compact([
    section('keyword-suggestions', '关键词生成参数', [
      item('projectName', '项目名称', project.name),
      item('projectDescription', '项目说明', project.description),
      item('referenceSources', '参考来源', listText(configuration.reference_sources)),
      item('referenceKeywords', '参考关键词', listText(configuration.reference_keywords)),
      item('existingKeywordCount', '去重关键词数', Array.isArray(configuration.existing_keywords)
        ? configuration.existing_keywords.length
        : undefined),
    ]),
  ]);
}

function commentSections(task: Task): TaskInputPresentationSection[] {
  const input = task.input_json;
  const configuration: Record<string, unknown> = isRecord(input.post_comments)
    ? input.post_comments
    : {};
  const snapshot: Record<string, unknown> = isRecord(input.post_snapshot)
    ? input.post_snapshot
    : {};
  return compact([
    section('comments', '评论采集参数', [
      item('postTitle', '帖子', snapshot.title),
      item('noteId', '帖子 ID', snapshot.note_id),
      item(
        'collectionMode',
        '采集方式',
        configuration.collection_mode === 'refresh' ? '重新更新' : '继续补充',
      ),
      item('requestedPages', '计划抓取页数', configuration.requested_pages),
      item(
        'pageDelay',
        '页间安全间隔',
        `${text(configuration.page_delay_min_seconds) ?? '1'}～${text(configuration.page_delay_max_seconds) ?? '2'} 秒`,
      ),
      item(
        'replyScope',
        '回复范围',
        configuration.include_sub_comments
          ? `抓取楼中楼，最多 ${text(configuration.sub_comment_page_limit) ?? '20'} 个请求页`
          : '仅保存接口随一级评论附带的回复预览',
      ),
    ]),
  ]);
}

export function taskInputPresentation(task: Task): TaskInputPresentation {
  const sections =
    task.task_type === 'vision'
      ? visionSections(task)
      : task.task_type === 'ai_report'
        ? reportSections(task)
        : task.task_type === 'keyword_suggestions'
          ? keywordSuggestionSections(task)
          : task.task_type === 'comments'
            ? commentSections(task)
            : researchSections(task);

  return {
    sections,
    rawJson: JSON.stringify(task.input_json ?? {}, null, 2),
  };
}
