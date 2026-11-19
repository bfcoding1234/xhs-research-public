import { ProFormDigit, ProFormSelect, ProFormTextArea } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import type { FormInstance } from 'antd';
import { Alert, Card, Checkbox, Form, Switch, Tag, Typography } from 'antd';
import type { AppSettings, Author, ResearchType } from '@/types';
import AuthorCandidatePicker from './AuthorCandidatePicker';
import {
  invalidAuthorSourceValues,
  maxAuthorNotes,
  normalizeAuthorSourceValues,
  resolveAuthorProfileUrls,
  sourceLimit,
  splitSourceValues,
} from './configuration';
import styles from './research.module.css';
import type { ResearchFormValues, SourceFieldValue } from './types';
import { apiService } from '@/services/api';
import { queryKeys } from '@/services/queryKeys';

interface ResearchFieldsProps {
  mode: ResearchType;
  settings: AppSettings;
  form: FormInstance<ResearchFormValues>;
  projectId?: number;
  candidateAuthors?: Author[];
  maxAuthors?: number;
}

function sourceRules(
  requiredMessage: string | undefined,
  limit: number,
  parseValues: (value: SourceFieldValue) => string[] = splitSourceValues,
  validateValues?: (value: SourceFieldValue) => string | undefined,
) {
  return [
    {
      validator: (_: unknown, value: SourceFieldValue) => {
        const count = parseValues(value).length;
        if (requiredMessage && count === 0) return Promise.reject(new Error(requiredMessage));
        if (count > limit) {
          return Promise.reject(new Error(`超过后台配置的单次来源上限 ${limit}`));
        }
        const validationError = validateValues?.(value);
        if (validationError) return Promise.reject(new Error(validationError));
        return Promise.resolve();
      },
    },
  ];
}

export default function ResearchFields({
  mode,
  settings,
  form,
  projectId,
  candidateAuthors = [],
  maxAuthors,
}: ResearchFieldsProps) {
  const showKeywords = mode === 'keyword' || mode === 'mixed';
  const showAuthors = mode === 'author' || mode === 'mixed';
  const keywordValue = Form.useWatch('keywords', form) as SourceFieldValue;
  const authorValue = Form.useWatch('authors', form) as SourceFieldValue;
  const userKeywordValue = Form.useWatch('userKeywords', form) as SourceFieldValue;
  const collectKeywordPostsValue = Form.useWatch('keywordCollectPosts', form);
  const collectKeywordPosts = mode !== 'keyword' || collectKeywordPostsValue !== false;
  const collectKeywordAuthors = Boolean(Form.useWatch('keywordCollectAuthors', form));
  const keywordCount = splitSourceValues(keywordValue).length;
  const authorCount = normalizeAuthorSourceValues(authorValue).length;
  const userKeywordCount = splitSourceValues(userKeywordValue).length;
  const authorProfileUrls = resolveAuthorProfileUrls(authorValue);
  const keywordLimit = sourceLimit(settings, 'max_keywords_per_task');
  const authorLimit = Math.min(
    sourceLimit(settings, 'max_authors_per_task'),
    maxAuthors ?? Number.POSITIVE_INFINITY,
  );
  const authorNoteLimit = maxAuthorNotes(settings);
  const watchedProjectId = Form.useWatch('projectId', form);
  const selectedProjectId = projectId ?? watchedProjectId;
  const projectKeywords = useQuery({
    queryKey: queryKeys.projectKeywords(selectedProjectId ?? 'none'),
    queryFn: ({ signal }) => apiService.projectKeywords(String(selectedProjectId ?? ''), signal),
    enabled: Boolean(selectedProjectId) && mode === 'keyword',
  });
  const projectAuthors = useQuery({
    queryKey: queryKeys.projectAuthors(selectedProjectId ?? 'none'),
    queryFn: ({ signal }) => apiService.projectAuthors(String(selectedProjectId ?? ''), signal),
    enabled: Boolean(selectedProjectId) && mode === 'author' && candidateAuthors.length === 0,
  });
  const availableCandidateAuthors = candidateAuthors.length > 0 ? candidateAuthors : projectAuthors.data ?? [];

  return (
    <div className={styles.sectionStack}>
      {showKeywords ? (
        <Card
          size="small"
          className={styles.sectionCard}
          title="关键词搜索"
          extra={
            <Tag
              className={styles.countTag}
              color={keywordCount > keywordLimit ? 'error' : 'default'}
            >
              {keywordCount}/{keywordLimit} 个
            </Tag>
          }
        >
          {selectedProjectId ? (
            <ProFormSelect
              name="projectKeywords"
              label="从项目关键词库选择"
              options={(projectKeywords.data ?? []).map((keyword) => ({
                value: keyword.keyword,
                label: keyword.keyword,
              }))}
              fieldProps={{
                mode: 'multiple',
                allowClear: true,
                loading: projectKeywords.isPending,
                placeholder: '选择当前项目已维护的关键词（可选）',
              }}
              extra="所选关键词会与手动输入合并并自动去重，不会修改项目关键词库。"
            />
          ) : null}
          {projectKeywords.isError ? (
            <Alert
              type="warning"
              showIcon
              title="项目关键词暂时无法加载"
              description="仍可手动输入关键词后创建任务。"
            />
          ) : null}
          <ProFormSelect
            name="keywords"
            label="关键词"
            rules={sourceRules(
              mode === 'keyword' ? '请至少填写一个关键词' : undefined,
              keywordLimit,
            )}
            extra="输入后按回车添加，也可以粘贴以逗号或换行分隔的多个关键词。"
            fieldProps={{
              mode: 'tags',
              tokenSeparators: [',', '，', '\n'],
              maxTagCount: 'responsive',
              placeholder: '例如：AI 产品经理、AI 职业发展',
            }}
          />
          {mode === 'keyword' ? (
            <section className={styles.collectionScopes} aria-label="关键词采集范围">
              <Typography.Text strong>采集范围</Typography.Text>
              <div className={styles.collectionScopeGrid}>
                <section className={styles.collectionScope}>
                  <Form.Item
                    name="keywordCollectPosts"
                    label="采集帖子"
                    valuePropName="checked"
                    extra="按关键词搜索并采集帖子信息。"
                  >
                    <Switch checkedChildren="开启" unCheckedChildren="关闭" />
                  </Form.Item>
                  {collectKeywordPosts ? (
                    <div className={styles.fieldGrid}>
                      <ProFormDigit
                        name="keywordDiscovery"
                        label="每个关键词发现数量"
                        min={1}
                        fieldProps={{ precision: 0 }}
                        rules={[{ required: true, message: '请填写发现数量' }]}
                      />
                      <ProFormDigit
                        name="keywordDeep"
                        label="每个关键词深度分析数量"
                        min={0}
                        fieldProps={{ precision: 0 }}
                        rules={[{ required: true, message: '请填写深度分析数量' }]}
                      />
                      <ProFormSelect
                        name="sort"
                        label="排序方式"
                        options={[
                          { value: '综合', label: '综合' },
                          { value: '最新', label: '最新' },
                          { value: '最热', label: '最热' },
                        ]}
                        rules={[{ required: true }]}
                      />
                      <ProFormSelect
                        name="publishTime"
                        label="发布时间"
                        options={[
                          { value: '不限', label: '不限' },
                          { value: '一天内', label: '一天内' },
                          { value: '一周内', label: '一周内' },
                          { value: '半年内', label: '半年内' },
                        ]}
                        rules={[{ required: true }]}
                      />
                    </div>
                  ) : null}
                </section>
                <section className={styles.collectionScope}>
                  <Form.Item
                    name="keywordCollectAuthors"
                    label="采集作者"
                    valuePropName="checked"
                    extra="按同一组关键词搜索相关作者；不会读取这些作者主页下的帖子。"
                  >
                    <Switch checkedChildren="开启" unCheckedChildren="关闭" />
                  </Form.Item>
                  {collectKeywordAuthors ? (
                    <ProFormDigit
                      name="keywordAuthorLimit"
                      label="最多采集作者数"
                      min={1}
                      fieldProps={{ precision: 0 }}
                      extra="不设固定上限；默认值可在后台参数配置中调整。"
                      rules={[
                        { required: true, message: '请填写最多采集作者数' },
                        {
                          type: 'number',
                          min: 1,
                          message: '最多采集作者数不能小于 1',
                        },
                      ]}
                    />
                  ) : null}
                </section>
              </div>
              {!collectKeywordPosts && !collectKeywordAuthors ? (
                <Alert
                  type="warning"
                  showIcon
                  title="请至少开启一种采集范围"
                  description="关键词任务需要采集相关帖子、相关作者，或同时采集两者。"
                />
              ) : null}
            </section>
          ) : null}
          {mode !== 'keyword' && collectKeywordPosts ? (
            <div className={styles.fieldGrid}>
              <ProFormDigit
                name="keywordDiscovery"
                label="每个关键词发现数量"
                min={1}
                fieldProps={{ precision: 0 }}
                rules={[{ required: true, message: '请填写发现数量' }]}
              />
              <ProFormDigit
                name="keywordDeep"
                label="每个关键词深度分析数量"
                min={0}
                fieldProps={{ precision: 0 }}
                rules={[{ required: true, message: '请填写深度分析数量' }]}
              />
              <ProFormSelect
                name="sort"
                label="排序方式"
                options={[
                  { value: '综合', label: '综合' },
                  { value: '最新', label: '最新' },
                  { value: '最热', label: '最热' },
                ]}
                rules={[{ required: true }]}
              />
              <ProFormSelect
                name="publishTime"
                label="发布时间"
                options={[
                  { value: '不限', label: '不限' },
                  { value: '一天内', label: '一天内' },
                  { value: '一周内', label: '一周内' },
                  { value: '半年内', label: '半年内' },
                ]}
                rules={[{ required: true }]}
              />
            </div>
          ) : null}
        </Card>
      ) : null}

      {showAuthors ? (
        <Card
          size="small"
          className={styles.sectionCard}
          title="作者调研"
          extra={
            <Tag
              className={styles.countTag}
              color={authorCount > authorLimit ? 'error' : 'default'}
            >
              {authorCount}/{authorLimit} 位
            </Tag>
          }
        >
          <section className={styles.authorSource} aria-label="选择或输入作者">
            <Typography.Text strong>选择或输入作者</Typography.Text>
            {availableCandidateAuthors.length > 0 ? (
              <AuthorCandidatePicker
                authors={availableCandidateAuthors}
                form={form}
                maxSelection={authorLimit}
              />
            ) : null}
            <ProFormTextArea
              name="authors"
              label={availableCandidateAuthors.length > 0 ? '也可以手动输入作者' : '作者主页 URL 或作者 ID'}
              rules={sourceRules(
                undefined,
                authorLimit,
                normalizeAuthorSourceValues,
                (value) =>
                  invalidAuthorSourceValues(value).length > 0
                    ? '作者来源只能填写小红书作者主页 URL 或不含路径的作者 ID'
                    : undefined,
              )}
              extra={
                maxAuthors === 1
                  ? '“个人项目”每次只调研一位作者；可以在更新调研时更换。'
                  : '支持多位作者，每行填写一个主页 URL 或作者 ID。'
              }
              fieldProps={{
                rows: 4,
                placeholder:
                  'https://www.xiaohongshu.com/user/profile/…\n另一位作者主页 URL 或作者 ID',
              }}
            />
            {authorProfileUrls.length > 0 ? (
              <nav className={styles.resolvedProfiles} aria-label="已解析的作者主页">
                <Typography.Text type="secondary">已解析主页</Typography.Text>
                <div className={styles.resolvedProfileLinks}>
                  {authorProfileUrls.map((profileUrl) => (
                    <Typography.Link
                      key={profileUrl}
                      href={profileUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {profileUrl}
                    </Typography.Link>
                  ))}
                </div>
              </nav>
            ) : null}
          </section>
          {maxAuthors !== 1 ? (
            <>
              <ProFormSelect
                name="userKeywords"
                label="按关键词发现用户"
                rules={sourceRules(undefined, keywordLimit)}
                extra={`可输入 ${keywordLimit} 个关键词；系统最多选取下方设置数量的用户。`}
                fieldProps={{
                  mode: 'tags',
                  tokenSeparators: [',', '，', '\n'],
                  maxTagCount: 'responsive',
                  placeholder: '例如：AI 产品经理、独立开发者',
                }}
              />
              <ProFormDigit
                name="userDiscovery"
                label="最多发现用户数"
                min={1}
                max={authorLimit}
                fieldProps={{ precision: 0 }}
                rules={[{ required: true, message: '请填写最多发现用户数' }]}
              />
              <Alert
                type="info"
                showIcon
                title={`已填写 ${userKeywordCount} 个用户关键词`}
                description="“按关键词发现用户”会调用 xiaohongshu-cli；发现用户后，主页帖子与详情会继续由各自最合适的原子能力执行。任务不会整体绑定某个采集引擎。"
              />
            </>
          ) : null}
          {mode === 'author' ? (
            <>
              <Form.Item
                name="authorScopes"
                label="采集内容"
                rules={[
                  { required: true, type: 'array', min: 1, message: '请至少选择一项作者采集内容' },
                ]}
                extra="基础用户信息默认选中；只有选择用户帖子信息后才会读取作者主页帖子。"
              >
                <Checkbox.Group
                  options={[
                    { value: 'basic_info', label: '基础用户信息' },
                    { value: 'posts', label: '用户帖子信息' },
                  ]}
                />
              </Form.Item>
              <Form.Item
                noStyle
                shouldUpdate={(previous, current) => previous.authorScopes !== current.authorScopes}
              >
                {({ getFieldValue }) =>
                  (getFieldValue('authorScopes') ?? []).includes('posts') ? (
                    <div className={styles.fieldGrid}>
                      <ProFormDigit
                        name="authorDiscovery"
                        label="每位作者发现数量"
                        min={1}
                        max={authorNoteLimit}
                        fieldProps={{ precision: 0 }}
                        extra={`后台作者采集硬上限为 ${authorNoteLimit}`}
                        rules={[
                          { required: true, message: '请填写发现数量' },
                          {
                            type: 'number',
                            min: 1,
                            max: authorNoteLimit,
                            message: `作者发现数量需要在 1–${authorNoteLimit} 之间`,
                          },
                        ]}
                      />
                      <ProFormDigit
                        name="authorDeep"
                        label="每位作者深度分析数量"
                        min={0}
                        max={authorNoteLimit}
                        fieldProps={{ precision: 0 }}
                        rules={[
                          { required: true, message: '请填写深度分析数量' },
                          {
                            type: 'number',
                            min: 0,
                            max: authorNoteLimit,
                            message: `作者深度分析数量需要在 0–${authorNoteLimit} 之间`,
                          },
                        ]}
                      />
                    </div>
                  ) : null
                }
              </Form.Item>
            </>
          ) : (
            <div className={styles.fieldGrid}>
              <ProFormDigit
                name="authorDiscovery"
                label="每位作者发现数量"
                min={1}
                max={authorNoteLimit}
                fieldProps={{ precision: 0 }}
                extra={`后台作者采集硬上限为 ${authorNoteLimit}`}
                rules={[{ required: true, message: '请填写发现数量' }]}
              />
              <ProFormDigit
                name="authorDeep"
                label="每位作者深度分析数量"
                min={0}
                max={authorNoteLimit}
                fieldProps={{ precision: 0 }}
                rules={[{ required: true, message: '请填写深度分析数量' }]}
              />
            </div>
          )}
        </Card>
      ) : null}

    </div>
  );
}
