import { Collapse, Empty, Tag, Typography } from 'antd';
import type { VisionAnalysis } from '@/types';
import { formatDate } from '@/utils/format';

const { Text, Title } = Typography;

function AnalysisFact({ label, children }: { label: string; children?: React.ReactNode }) {
  return (
    <div className="post-detail-fact">
      <Text type="secondary">{label}</Text>
      <div className="post-detail-fact-value">{children || '—'}</div>
    </div>
  );
}

function InsightList({ title, values }: { title: string; values?: string[] }) {
  if (!values?.length) return null;
  return (
    <section className="post-detail-insight-list">
      <Text strong>{title}</Text>
      <ul>
        {values.map((value) => (
          <li key={value}>{value}</li>
        ))}
      </ul>
    </section>
  );
}

function modelLabel(model: string) {
  return model === 'default' ? 'Codex 默认模型' : model;
}

export default function VisionAnalysisSection({
  analyses,
  compact = false,
}: {
  analyses?: VisionAnalysis[];
  compact?: boolean;
}) {
  const content = analyses?.length ? (
    <Collapse
      className="post-detail-vision-collapse"
      defaultActiveKey={[String(analyses[0]?.id)]}
      items={analyses.map((analysis) => ({
        key: String(analysis.id),
        label: `分析 ${formatDate(analysis.analyzed_at)}`,
        extra: <Tag color="geekblue">模型：{modelLabel(analysis.model)}</Tag>,
        children: (
          <article className="post-detail-vision-card" key={analysis.id}>
            <div className="post-detail-analysis-meta">
              <div className="post-detail-analysis-source">
                <Tag>Prompt：{analysis.prompt_version}</Tag>
              </div>
              <Text type="secondary">分析时间：{formatDate(analysis.analyzed_at)}</Text>
            </div>

            <div className="post-detail-analysis-grid">
              <AnalysisFact label="封面钩子">{analysis.analysis_json.cover_hook}</AnalysisFact>
              <AnalysisFact label="视觉风格">{analysis.analysis_json.visual_style}</AnalysisFact>
              <AnalysisFact label="版式结构">{analysis.analysis_json.layout}</AnalysisFact>
              <AnalysisFact label="信息密度">
                {analysis.analysis_json.information_density}
              </AnalysisFact>
              <AnalysisFact label="情绪氛围">{analysis.analysis_json.emotion}</AnalysisFact>
            </div>

            <div className="post-detail-insight-grid">
              <InsightList title="可信信号" values={analysis.analysis_json.credibility_signals} />
              <InsightList title="适合受众" values={analysis.analysis_json.suitable_audience} />
              <InsightList title="可复用模式" values={analysis.analysis_json.reusable_patterns} />
              <InsightList title="可改进问题" values={analysis.analysis_json.problems} />
            </div>
          </article>
        ),
      }))}
    />
  ) : (
    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未补充大模型图片理解" />
  );

  if (compact) return <div className="post-detail-vision-panel">{content}</div>;

  return (
    <section className="post-detail-section post-detail-vision-section" data-testid="vision-analysis-section">
      <div className="post-detail-section-heading">
        <Text className="post-detail-eyebrow">AI VISUAL ANALYSIS</Text>
        <Title level={3}>大模型图片理解</Title>
        <Text type="secondary">
          基于当前本地图片，从封面钩子、视觉风格、版式、受众与可复用模式等维度解读画面。
        </Text>
      </div>

      {content}
    </section>
  );
}
