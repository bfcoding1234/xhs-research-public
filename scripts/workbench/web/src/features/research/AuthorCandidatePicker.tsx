import type { FormInstance } from 'antd';
import { App, Button, Checkbox, Empty, Form, Input, Tag, Typography } from 'antd';
import { useMemo, useState } from 'react';
import type { Author } from '@/types';
import { rankCandidateAuthors, recommendedAuthorIds } from '@/utils/authors';
import { formatNumber } from '@/utils/format';
import { splitSourceValues } from './configuration';
import styles from './research.module.css';
import type { ResearchFormValues } from './types';

const { Paragraph, Text } = Typography;

interface AuthorCandidatePickerProps {
  authors: Author[];
  form: FormInstance<ResearchFormValues>;
  maxSelection: number;
}

export function authorIdentity(value: unknown): string {
  const text = String(value ?? '').trim();
  const match = text.match(/\/user\/profile\/([^/?#]+)/);
  if (!match?.[1]) return text;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

export default function AuthorCandidatePicker({
  authors,
  form,
  maxSelection,
}: AuthorCandidatePickerProps) {
  const { message } = App.useApp();
  const [query, setQuery] = useState('');
  const [recommendedOnly, setRecommendedOnly] = useState(false);
  const fieldValue = Form.useWatch('authors', form);
  const sourceValues = useMemo(() => splitSourceValues(fieldValue), [fieldValue]);
  const selected = useMemo(
    () => new Set(sourceValues.map((value) => authorIdentity(value))),
    [sourceValues],
  );
  const ranked = useMemo(() => rankCandidateAuthors(authors), [authors]);
  const recommended = useMemo(
    () => recommendedAuthorIds(authors, Math.min(5, maxSelection)),
    [authors, maxSelection],
  );

  const normalizedQuery = query.trim().toLocaleLowerCase('zh-CN');
  const visible = ranked
    .map((author, index) => ({ ...author, candidateRank: index + 1 }))
    .filter((author) => {
      const matchesRecommendation = !recommendedOnly || recommended.has(author.author_id);
      const haystack = `${author.display_name || ''} ${author.author_id || ''}`.toLocaleLowerCase(
        'zh-CN',
      );
      return matchesRecommendation && (!normalizedQuery || haystack.includes(normalizedQuery));
    });

  const setCandidateSelection = (ids: Set<string>) => {
    const candidateIds = new Set(
      authors.flatMap((author) => [author.author_id, authorIdentity(author.profile_url)]),
    );
    const manual = sourceValues.filter((value) => !candidateIds.has(authorIdentity(value)));
    const availableSlots = Math.max(0, maxSelection - manual.length);
    const chosen = ranked
      .filter((author) => ids.has(author.author_id))
      .slice(0, availableSlots)
      .map((author) => author.profile_url || author.author_id);
    form.setFieldsValue({ authors: [...new Set([...manual, ...chosen])].join('\n') });
    form.validateFields(['authors']).catch(() => undefined);
  };

  const toggle = (author: Author, checked: boolean) => {
    const next = new Set(selected);
    if (checked) {
      if (sourceValues.length >= maxSelection && !next.has(author.author_id)) {
        message.warning(`本次最多可选择 ${maxSelection} 位作者`);
        return;
      }
      next.add(author.author_id);
    } else {
      next.delete(author.author_id);
    }
    setCandidateSelection(next);
  };

  const selectedCandidates = ranked.filter((author) => selected.has(author.author_id)).length;

  return (
    <section className={styles.authorPicker} aria-label="项目已有作者候选">
      <div className={styles.authorPickerHeading}>
        <div className={styles.authorPickerCopy}>
          <Text strong>从项目已有作者中选择</Text>
          <Paragraph type="secondary" style={{ margin: '4px 0 0' }}>
            优先参考热门内容数量和最高热度，再参考粉丝与获赞收藏；排序只用于辅助判断。
          </Paragraph>
        </div>
        <Text type="secondary">
          已选候选 {selectedCandidates} 位 · 来源共 {sourceValues.length}/{maxSelection} 位
        </Text>
      </div>

      <div className={styles.authorPickerControls}>
        <Input.Search
          allowClear
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索作者名称或 ID"
          style={{ width: 'min(100%, 260px)' }}
        />
        <Checkbox
          checked={recommendedOnly}
          onChange={(event) => setRecommendedOnly(event.target.checked)}
        >
          只看优先推荐
        </Checkbox>
        <Button size="small" onClick={() => setCandidateSelection(recommended)}>
          选择优先推荐
        </Button>
        <Button size="small" onClick={() => setCandidateSelection(new Set())}>
          清空候选
        </Button>
      </div>

      <div className={styles.candidateList}>
        {visible.map((author) => {
          const isRecommended = recommended.has(author.author_id);
          const peak = Math.round(Number(author.peak_popularity_percentile || 0) * 100);
          return (
            <div className={styles.candidateCard} key={author.author_id}>
              <Checkbox
                aria-label={`选择作者 ${author.display_name || author.author_id}`}
                checked={selected.has(author.author_id)}
                onChange={(event) => toggle(author, event.target.checked)}
              />
              <div>
                <div className={styles.candidateHeading}>
                  <span>
                    <Text strong>{author.display_name || author.author_id}</Text>
                    {isRecommended ? (
                      <Tag color="blue" style={{ marginInlineStart: 8 }}>
                        优先 {author.candidateRank}
                      </Tag>
                    ) : null}
                  </span>
                  <Text className={styles.candidateScore}>
                    优先度 {formatNumber(author.selection_priority)}
                  </Text>
                </div>
                <div className={styles.candidateMetrics}>
                  <Tag>{formatNumber(author.hot_post_count)} 篇较热/高热帖</Tag>
                  <Tag>最高热度 {peak}%</Tag>
                  <Tag>{formatNumber(author.followers_count)} 粉丝</Tag>
                  <Tag>{formatNumber(author.project_post_count)} 篇项目帖子</Tag>
                </div>
              </div>
            </div>
          );
        })}
        {visible.length === 0 ? (
          <div className={styles.emptyCandidates}>
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有符合条件的作者" />
          </div>
        ) : null}
      </div>
    </section>
  );
}
