import { describe, expect, it } from 'vitest';
import type { Task } from '@/types';
import { taskInputPresentation } from './taskInputPresentation';

function task(values: Partial<Task> = {}): Task {
  return {
    id: 'task-1',
    project_id: 1,
    author_id: null,
    task_type: 'research',
    mode: 'keyword',
    created_from: 'web',
    input_json: {},
    status: 'queued',
    current_phase: 'queued',
    progress_current: 0,
    progress_total: 0,
    warning_count: 0,
    error_message: '',
    result_json: {},
    created_at: '2026-07-17T00:00:00Z',
    started_at: null,
    finished_at: null,
    ...values,
  };
}

describe('taskInputPresentation', () => {
  it('把采集任务输入展示为可读分组', () => {
    const result = taskInputPresentation(
      task({
        input_json: {
          topic: 'AI 产品经理内容趋势',
          source: {
            keywords: ['AI 产品经理', 'AI Agent'],
            profile_urls: ['https://www.xiaohongshu.com/user/profile/author-a'],
            user_keywords: ['独立开发者'],
            filters: { sort: '综合', publish_time: '不限' },
          },
          limits: { discovery: 20, deep: 5 },
          keyword_limits: { discovery: 20, deep: 5 },
          author_limits: { discovery: 80, deep: 5 },
          user_limits: { discovery: 3 },
          force_refresh: false,
        },
      }),
    );

    expect(result.sections.map((section) => section.title)).toEqual([
      '基本信息',
      '数据来源',
      '数量与规则',
    ]);
    expect(result.sections[0]?.items).toContainEqual({
      key: 'topic',
      label: '采集主题',
      value: 'AI 产品经理内容趋势',
    });
    expect(result.sections[1]?.items).toContainEqual({
      key: 'keywords',
      label: '关键词',
      value: 'AI 产品经理、AI Agent',
    });
    expect(result.sections[2]?.items).toContainEqual({
      key: 'authorLimits',
      label: '作者数量（发现 / 深度）',
      value: '80 / 5',
    });
  });

  it('展示作者更新任务的更新范围', () => {
    const result = taskInputPresentation(
      task({
        mode: 'author',
        input_json: {
          source: { profile_urls: [], author_ids: ['author-a'], keywords: [], filters: {} },
          limits: { discovery: 80, deep: 5 },
          author_update: { scopes: ['preview_posts', 'detailed_posts'] },
          force_refresh: true,
        },
      }),
    );

    expect(result.sections[0]?.items).toContainEqual({
      key: 'authorUpdateScopes',
      label: '更新范围',
      value: '预览帖子、详细帖子',
    });
  });

  it('展示图片理解任务参数', () => {
    const result = taskInputPresentation(
      task({
        task_type: 'vision',
        input_json: {
          image_analysis: {
            mode: 'vision-selective',
            only_unanalyzed: true,
            vision_ratio: 0.2,
            vision_count: 10,
            vision_max_count: 30,
            vision_batch_size: 5,
          },
        },
      }),
    );

    expect(result.sections[0]?.items).toContainEqual({
      key: 'imageScopes',
      label: '图片范围',
      value: '全部图片（历史默认）',
    });
    expect(result.sections[0]?.items).toContainEqual({
      key: 'mode',
      label: '帖子选择',
      value: '选择性分析未处理图片',
    });
    expect(result.sections[0]?.items).toContainEqual({
      key: 'ratio',
      label: '选择比例',
      value: '20%',
    });
  });

  it('展示大模型报告任务参数', () => {
    const result = taskInputPresentation(
      task({
        task_type: 'ai_report',
        author_id: 3,
        project_id: null,
        input_json: {
          report_scope: 'author',
          report_generation: {
            title: '作者报告',
            instructions: '关注选题方向',
            context_detail: 'detailed',
          },
        },
      }),
    );

    expect(result.sections[0]?.items).toEqual([
      { key: 'scope', label: '报告范围', value: '作者' },
      { key: 'title', label: '报告标题', value: '作者报告' },
      { key: 'instructions', label: '补充要求', value: '关注选题方向' },
      { key: 'contextDetail', label: '输入上下文', value: '深入' },
    ]);
  });

  it('展示精确报告上下文来源、比例和帖子字段', () => {
    const result = taskInputPresentation(task({
      task_type: 'ai_report',
      input_json: {
        report_generation: {
          title: '精确上下文报告',
          context_config: {
            authors: { enabled: false },
            posts: {
              enabled: true,
              selection_mode: 'expanded',
              sections: ['basic', 'content', 'ocr'],
            },
          },
        },
      },
    }));

    expect(result.sections[0]?.items).toContainEqual({
      key: 'contextDetail',
      label: '输入上下文',
      value: '当前明细：帖子（50%；基础信息、正文、OCR 文本）',
    });
  });

  it('把 HTML 演示稿与文字报告任务参数区分展示', () => {
    const result = taskInputPresentation(task({
      task_type: 'ai_report',
      input_json: {
        operation: 'html_presentation',
        report_scope: 'project',
        presentation_generation: {
          title: '管理层汇报演示稿',
          page_mode: 'standard',
          instructions: '突出行动建议',
          source_report: {
            id: 17,
            version: 2,
            title: '内容机会报告',
          },
        },
      },
    }));

    expect(result.sections[0]?.title).toBe('HTML 演示稿参数');
    expect(result.sections[0]?.items).toEqual([
      { key: 'scope', label: '报告范围', value: '项目' },
      { key: 'sourceReport', label: '源文字报告', value: '内容机会报告' },
      { key: 'sourceVersion', label: '源报告版本', value: '2' },
      { key: 'title', label: '演示稿标题', value: '管理层汇报演示稿' },
      { key: 'pageMode', label: '篇幅', value: '标准（9～12 页）' },
      { key: 'instructions', label: '补充要求', value: '突出行动建议' },
    ]);
  });

  it('展示 AI 关键词生成任务的快照', () => {
    const result = taskInputPresentation(task({
      task_type: 'keyword_suggestions',
      input_json: {
        keyword_suggestions: {
          project: { name: 'AI 产品经理', description: '研究工作方式变化' },
          reference_sources: ['manual'],
          reference_keywords: ['产品经理转型'],
          existing_keywords: ['产品经理转型', 'AI 工作流'],
        },
      },
    }));

    expect(result.sections[0]?.items).toContainEqual({
      key: 'referenceKeywords', label: '参考关键词', value: '产品经理转型',
    });
    expect(result.sections[0]?.items).toContainEqual({
      key: 'existingKeywordCount', label: '去重关键词数', value: '2',
    });
  });

  it('展示项目作者批量更新任务参数', () => {
    const result = taskInputPresentation(
      task({
        project_id: 9,
        mode: 'author',
        input_json: {
          operation: 'project_author_update',
          author_update_bulk: {
            target: 'basic_unupdated',
            scopes: ['basic_info', 'preview_posts'],
            author_ids: ['author-a', 'author-b'],
            batch_size: 10,
            max_authors: 100,
            preview_limit: 20,
            detail_limit: 5,
            author_delay_min_seconds: 5,
            author_delay_max_seconds: 15,
            batch_delay_min_seconds: 60,
            batch_delay_max_seconds: 180,
            consecutive_failure_limit: 5,
          },
        },
      }),
    );

    expect(result.sections[0]?.items).toContainEqual({
      key: 'target',
      label: '目标作者',
      value: '基础信息未更新的作者',
    });
    expect(result.sections[0]?.items).toContainEqual({
      key: 'authorCount',
      label: '本次作者数',
      value: '2',
    });
    expect(result.sections[1]?.items).toContainEqual({
      key: 'authorDelay',
      label: '作者间隔',
      value: '5～15 秒',
    });
  });

  it('展示帖子详情批量更新任务参数', () => {
    const result = taskInputPresentation(
      task({
        input_json: {
          operation: 'post_detail_update',
          post_detail_update: {
            mode: 'batch',
            scope: 'project',
            target: 'needs_update',
            post_ids: [1, 2, 3],
            max_posts: 300,
            batch_size: 10,
            post_delay_min_seconds: 5,
            post_delay_max_seconds: 15,
            batch_delay_min_seconds: 60,
            batch_delay_max_seconds: 180,
            consecutive_failure_limit: 5,
          },
        },
      }),
    );

    expect(result.sections[0]?.items).toContainEqual({
      key: 'target',
      label: '目标帖子',
      value: '需要补全或详情已过期的帖子',
    });
    expect(result.sections[0]?.items).toContainEqual({
      key: 'postCount',
      label: '本次帖子数',
      value: '3',
    });
    expect(result.sections[1]?.items).toContainEqual({
      key: 'postDelay',
      label: '帖子间隔',
      value: '5～15 秒',
    });
  });
});
