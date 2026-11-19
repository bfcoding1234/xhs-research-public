import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { VisionAnalysis } from '@/types';
import VisionAnalysisSection from './VisionAnalysisSection';

const analysis: VisionAnalysis = {
  id: 1,
  post_id: 13,
  model: 'gpt-5.2',
  prompt_version: 'vision-v2',
  analysis_json: {
    cover_hook: '数字标题制造明确收益预期',
    visual_style: '教程卡片',
    layout: '标题居中，产品界面作为证据',
    information_density: '中等',
    credibility_signals: ['真实产品界面', '步骤编号'],
    emotion: '轻松、可信',
    suitable_audience: ['新手用户'],
    reusable_patterns: ['收益标题 + 操作截图'],
    problems: ['辅助文字偏小'],
  },
  analyzed_at: '2026-07-10T21:00:49+00:00',
};

describe('VisionAnalysisSection', () => {
  it('renders model provenance and the structured visual analysis', () => {
    render(<VisionAnalysisSection analyses={[analysis]} />);

    expect(screen.getByRole('heading', { name: '大模型图片理解' })).toBeInTheDocument();
    expect(screen.getByText('模型：gpt-5.2')).toBeInTheDocument();
    expect(screen.getByText('Prompt：vision-v2')).toBeInTheDocument();
    expect(screen.getByText('数字标题制造明确收益预期')).toBeInTheDocument();
    expect(screen.getByText('真实产品界面')).toBeInTheDocument();
    expect(screen.getByText('收益标题 + 操作截图')).toBeInTheDocument();
  });

  it('explains when the post has no current analysis', () => {
    render(<VisionAnalysisSection analyses={[]} />);

    expect(screen.getByText('尚未补充大模型图片理解')).toBeInTheDocument();
  });
});
