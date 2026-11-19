import type { ReportPromptTemplates } from '@/types';

export const REPORT_PROMPT_TEMPLATE_MAX_LENGTH = 12_000;

export const REPORT_PROMPT_VARIABLES = {
  chunk: [
    ['subject_name', '项目或作者名称'],
    ['allowed_post_ids', '当前批次允许引用的帖子 ID'],
    ['user_instructions', '本次分析要求'],
    ['evidence_json', '当前批次证据 JSON'],
  ],
  final: [
    ['scope_label', '项目或作者'],
    ['subject_name', '项目或作者名称'],
    ['report_title', '报告名称'],
    ['context_label', '输入上下文详细度'],
    ['user_instructions', '本次分析要求'],
    ['evidence_json', '最终证据 JSON'],
  ],
} as const;

const REQUIRED_VARIABLES: Record<keyof ReportPromptTemplates, string[]> = {
  chunk: ['allowed_post_ids', 'evidence_json'],
  final: ['evidence_json'],
};

const RAW_TOKEN_PATTERN = /{{(.*?)}}/gs;

export function validateReportPromptTemplate(
  kind: keyof ReportPromptTemplates,
  value: string | undefined,
): string | undefined {
  const label = kind === 'chunk' ? '分批分析提示词' : '最终报告提示词';
  if (!value?.trim()) return `${label}不能为空`;
  if (value.length > REPORT_PROMPT_TEMPLATE_MAX_LENGTH) {
    return `${label}不能超过 ${REPORT_PROMPT_TEMPLATE_MAX_LENGTH} 字`;
  }
  const matches = [...value.matchAll(RAW_TOKEN_PATTERN)];
  if ((value.match(/{{/g) ?? []).length !== matches.length || (value.match(/}}/g) ?? []).length !== matches.length) {
    return `${label}包含未闭合的模板变量`;
  }
  const allowed = new Set<string>(REPORT_PROMPT_VARIABLES[kind].map(([name]) => name));
  const variables = new Set<string>();
  for (const match of matches) {
    const rawVariable = match[1] ?? '';
    const variable = rawVariable.trim();
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(variable)) {
      return `${label}包含无效模板变量：{{${rawVariable}}}`;
    }
    if (!allowed.has(variable)) return `${label}包含未知模板变量：${variable}`;
    variables.add(variable);
  }
  const missing = REQUIRED_VARIABLES[kind].filter((variable) => !variables.has(variable));
  if (missing.length) {
    return `${label}缺少必需模板变量：${missing.map((variable) => `{{${variable}}}`).join('、')}`;
  }
  return undefined;
}
