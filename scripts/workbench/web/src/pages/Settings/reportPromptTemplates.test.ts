import { describe, expect, it } from 'vitest';
import { validateReportPromptTemplate } from './reportPromptTemplates';

describe('report prompt template validation', () => {
  it('accepts supported variables and optional user instructions', () => {
    expect(
      validateReportPromptTemplate(
        'chunk',
        '{{subject_name}}\n{{user_instructions}}\n{{allowed_post_ids}}\n{{evidence_json}}',
      ),
    ).toBeUndefined();
    expect(validateReportPromptTemplate('final', '{{report_title}}\n{{evidence_json}}')).toBeUndefined();
  });

  it('rejects missing required variables', () => {
    expect(validateReportPromptTemplate('chunk', '{{evidence_json}}')).toContain(
      '{{allowed_post_ids}}',
    );
    expect(validateReportPromptTemplate('final', '{{report_title}}')).toContain('{{evidence_json}}');
  });

  it('rejects unknown and malformed variables', () => {
    expect(validateReportPromptTemplate('final', '{{unknown}}\n{{evidence_json}}')).toContain(
      '未知模板变量',
    );
    expect(validateReportPromptTemplate('final', '{{evidence_json}')).toContain('未闭合');
  });
});
