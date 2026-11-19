import { RobotOutlined } from '@ant-design/icons';
import {
  Alert,
  App,
  Button,
  Checkbox,
  List,
  Modal,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd';
import { useQuery } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { apiService } from '@/services/api';
import { queryKeys } from '@/services/queryKeys';
import type {
  KeywordSuggestionsResponse,
  KeywordSuggestionTaskResult,
  Project,
  ProjectKeyword,
  ProjectKeywordSource,
  TaskStatus,
} from '@/types';
import { formatDate } from '@/utils/format';
import {
  createKeywordSuggestionCache,
  loadKeywordSuggestionCache,
  normalizeKeyword,
  saveKeywordSuggestionCache,
  type KeywordSuggestionCache,
} from './keywordSuggestionCache';
import {
  clearKeywordSuggestionTask,
  loadKeywordSuggestionTask,
  saveKeywordSuggestionTask,
} from './keywordSuggestionTask';
import styles from './KeywordSuggestionsModal.module.css';

interface KeywordSuggestionsModalProps {
  project: Pick<Project, 'id' | 'name' | 'description'>;
  projectKeywords: ProjectKeyword[];
  open: boolean;
  onClose: () => void;
  onAdd: (keywords: string[], source: ProjectKeywordSource) => Promise<ProjectKeyword[]>;
  onAdded: (keywords: ProjectKeyword[]) => void;
}

type ModalStep = 'configure' | 'results';

const activeTaskStatuses = new Set<TaskStatus>(['queued', 'running', 'waiting_login']);

function keywordSuggestionsFromTask(result: KeywordSuggestionTaskResult): KeywordSuggestionsResponse | undefined {
  const value = result.keyword_suggestions;
  return value && Array.isArray(value.keywords) && Array.isArray(value.reference_sources)
    ? value
    : undefined;
}

export default function KeywordSuggestionsModal({
  project,
  projectKeywords,
  open,
  onClose,
  onAdd,
  onAdded,
}: KeywordSuggestionsModalProps) {
  const { message, modal } = App.useApp();
  const manualKeywords = projectKeywords.filter((keyword) => keyword.source === 'manual');
  const aiKeywords = projectKeywords.filter((keyword) => keyword.source === 'ai_generated');
  const defaultSources = useMemo<ProjectKeywordSource[]>(
    () => (manualKeywords.length ? ['manual'] : []),
    [manualKeywords.length],
  );
  const [cache, setCache] = useState<KeywordSuggestionCache>();
  const [step, setStep] = useState<ModalStep>('configure');
  const [referenceSources, setReferenceSources] =
    useState<ProjectKeywordSource[]>(defaultSources);
  const [taskId, setTaskId] = useState<string>();
  const [cancelling, setCancelling] = useState(false);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string>();
  const task = useQuery({
    queryKey: queryKeys.task(taskId ?? ''),
    queryFn: ({ signal }) => apiService.task(taskId ?? '', signal),
    enabled: open && Boolean(taskId),
    refetchInterval: (query) =>
      query.state.data && activeTaskStatuses.has(query.state.data.status) ? 1_500 : false,
  });
  const projectTasks = useQuery({
    queryKey: queryKeys.projectTasks(project.id),
    queryFn: ({ signal }) => apiService.projectTasks(project.id, signal),
    enabled: open && !taskId,
  });
  const generating = Boolean(taskId) && (!task.data || activeTaskStatuses.has(task.data.status));

  useEffect(() => {
    if (!open) return;
    const saved = loadKeywordSuggestionCache(project.id);
    setCache(saved);
    setReferenceSources(saved?.referenceSources ?? defaultSources);
    setStep(saved ? 'results' : 'configure');
    setTaskId(loadKeywordSuggestionTask(project.id));
    setCancelling(false);
    setError(undefined);
  }, [defaultSources, open, project.id]);

  useEffect(() => {
    if (!open || taskId) return;
    const activeTask = projectTasks.data?.find(
      (candidate) =>
        candidate.task_type === 'keyword_suggestions' && activeTaskStatuses.has(candidate.status),
    );
    if (!activeTask) return;
    saveKeywordSuggestionTask(project.id, activeTask.id);
    setTaskId(activeTask.id);
  }, [open, project.id, projectTasks.data, taskId]);

  const existingKeywords = useMemo(
    () => new Set(projectKeywords.map((keyword) => normalizeKeyword(keyword.keyword))),
    [projectKeywords],
  );

  const updateCache = useCallback(
    (next: KeywordSuggestionCache) => {
      setCache(next);
      saveKeywordSuggestionCache(project.id, next);
    },
    [project.id],
  );

  useEffect(() => {
    if (!taskId || !task.data || activeTaskStatuses.has(task.data.status)) return;
    clearKeywordSuggestionTask(project.id);
    setTaskId(undefined);
    if (task.data.status === 'completed') {
      const response = keywordSuggestionsFromTask(task.data.result_json as KeywordSuggestionTaskResult);
      if (!response) {
        setError('生成任务已完成，但候选结果格式无效');
        return;
      }
      const next = createKeywordSuggestionCache(response);
      updateCache(next);
      setReferenceSources(next.referenceSources);
      setStep('results');
      return;
    }
    if (task.data.status === 'cancelled') {
      setError('AI 关键词生成已取消');
      return;
    }
    setError(task.data.error_message || '生成候选关键词失败');
  }, [project.id, task.data, taskId, updateCache]);

  const generate = useCallback(async () => {
    setError(undefined);
    try {
      const receipt = await apiService.createProjectKeywordSuggestions(
        project.id,
        { reference_sources: referenceSources },
      );
      saveKeywordSuggestionTask(project.id, receipt.id);
      setTaskId(receipt.id);
    } catch (reason) {
      const text = reason instanceof Error ? reason.message : '生成候选关键词失败';
      setError(text);
    }
  }, [project.id, referenceSources]);

  const cancelGeneration = useCallback(async () => {
    if (!taskId || cancelling) return;
    setCancelling(true);
    try {
      await apiService.cancelTask(taskId);
      clearKeywordSuggestionTask(project.id);
      setTaskId(undefined);
      setError('AI 关键词生成已取消');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '取消生成失败');
    } finally {
      setCancelling(false);
    }
  }, [cancelling, project.id, taskId]);

  const confirmRegenerate = () => {
    if (!cache) {
      void generate();
      return;
    }
    modal.confirm({
      title: '重新生成候选关键词？',
      content: `新结果生成成功后，将替换当前缓存的 ${cache.keywords.length} 个候选词。生成失败时仍保留当前结果。`,
      okText: '重新生成',
      cancelText: '取消',
      onOk: () => {
        void generate();
      },
    });
  };

  const selectedKeywords = cache?.selectedKeywords ?? [];
  const addableSelected = cache?.keywords
    .filter((candidate) => selectedKeywords.includes(candidate.keyword))
    .filter((candidate) => !existingKeywords.has(normalizeKeyword(candidate.keyword))) ?? [];

  const selectCandidates = (next: string[]) => {
    if (!cache) return;
    updateCache({ ...cache, selectedKeywords: next });
  };

  const addSelected = async () => {
    if (!cache || !addableSelected.length) return;
    const before = existingKeywords;
    const requested = addableSelected.map((candidate) => candidate.keyword);
    setAdding(true);
    try {
      const result = await onAdd(requested, 'ai_generated');
      const resultByName = new Map(
        result.map((keyword) => [normalizeKeyword(keyword.keyword), keyword]),
      );
      const added = requested
        .filter((keyword) => !before.has(normalizeKeyword(keyword)))
        .map((keyword) => resultByName.get(normalizeKeyword(keyword)))
        .filter((keyword): keyword is ProjectKeyword => Boolean(keyword));
      const skipped = requested.length - added.length;
      onAdded(added);
      message.success(
        skipped
          ? `成功添加 ${added.length} 个，跳过 ${skipped} 个已有关键词`
          : `已添加 ${added.length} 个 AI 关键词`,
      );
      close();
    } catch {
      // The mutation already displays the backend error; keep the cached choices intact.
    } finally {
      setAdding(false);
    }
  };

  const close = () => {
    onClose();
  };

  const sourceOption = (
    source: ProjectKeywordSource,
    label: string,
    values: ProjectKeyword[],
  ) => (
    <div className={styles.sourceOption}>
      <Checkbox
        checked={referenceSources.includes(source)}
        disabled={!values.length || generating || adding}
        onChange={(event) =>
          setReferenceSources((current) =>
            event.target.checked
              ? [...new Set([...current, source])]
              : current.filter((value) => value !== source),
          )
        }
      >
        {label}（{values.length}）
      </Checkbox>
      {values.length ? (
        <Space wrap size={[4, 4]} className={styles.sourceKeywords}>
          {values.slice(0, 12).map((keyword) => (
            <Tag key={keyword.id}>{keyword.keyword}</Tag>
          ))}
          {values.length > 12 ? <Typography.Text type="secondary">等 {values.length} 个</Typography.Text> : null}
        </Space>
      ) : null}
    </div>
  );

  let content: ReactNode;
  let footer: ReactNode;
  if (generating) {
    content = (
      <div className={styles.generating}>
        <Space orientation="vertical" size="middle">
          <Spin size="large" />
          <Typography.Text strong>正在生成候选关键词……</Typography.Text>
          <Typography.Text type="secondary">
            已提交后台任务，完成后会自动显示候选词。正在参考项目名称与说明
            {referenceSources.includes('manual') ? `、手工关键词（${manualKeywords.length}）` : ''}
            {referenceSources.includes('ai_generated') ? `、AI 生成关键词（${aiKeywords.length}）` : ''}
          </Typography.Text>
        </Space>
      </div>
    );
    footer = (
      <div className={styles.footer}>
        <Button onClick={close}>后台继续</Button>
        <Button danger loading={cancelling} onClick={() => void cancelGeneration()}>
          取消生成
        </Button>
      </div>
    );
  } else if (step === 'configure') {
    content = (
      <div className={styles.content}>
        <div className={styles.projectContext}>
          <Typography.Text type="secondary">项目名称</Typography.Text>
          <Typography.Text strong>{project.name}</Typography.Text>
          <Typography.Text type="secondary">项目说明</Typography.Text>
          <Typography.Paragraph ellipsis={{ rows: 3 }} style={{ marginBottom: 0 }}>
            {project.description || '未填写项目说明'}
          </Typography.Paragraph>
        </div>
        <div className={styles.resultHeader}>
          <Typography.Text strong>参考来源</Typography.Text>
          <Typography.Text type="secondary">
            项目名称和说明始终参与生成；可额外选择关键词来源。两项都不选时，仅参考项目信息。
          </Typography.Text>
        </div>
        {sourceOption('manual', '手工关键词', manualKeywords)}
        {sourceOption('ai_generated', 'AI 生成关键词', aiKeywords)}
        {error ? (
          <Alert type="error" showIcon title="候选关键词生成失败" description={error} />
        ) : null}
      </div>
    );
    footer = (
      <div className={styles.footer}>
        <Button onClick={close}>取消</Button>
        <Button type="primary" icon={<RobotOutlined />} onClick={confirmRegenerate}>
          {cache ? '重新生成' : '生成候选关键词'}
        </Button>
      </div>
    );
  } else {
    const available = cache?.keywords.filter(
      (candidate) => !existingKeywords.has(normalizeKeyword(candidate.keyword)),
    ) ?? [];
    content = (
      <div className={styles.content}>
        <div className={styles.resultHeader}>
          <div className={styles.candidateTitle}>
            <Typography.Text strong>
              已生成 {cache?.keywords.length ?? 0} 个候选词
            </Typography.Text>
            <Typography.Text type="secondary">
              {cache ? `生成于 ${formatDate(cache.generatedAt)}` : ''}
            </Typography.Text>
          </div>
          <Typography.Text type="secondary">
            生成依据：项目名称与说明
            {cache?.referenceSources.includes('manual') ? `、手工关键词（${manualKeywords.length}）` : ''}
            {cache?.referenceSources.includes('ai_generated') ? `、AI 生成关键词（${aiKeywords.length}）` : ''}
          </Typography.Text>
        </div>
        {error ? (
          <Alert type="error" showIcon title="候选关键词生成失败" description={error} />
        ) : null}
        <div className={styles.resultActions}>
          <Space>
            <Button
              size="small"
              disabled={!available.length}
              onClick={() => selectCandidates(available.map((candidate) => candidate.keyword))}
            >
              全选
            </Button>
            <Button
              size="small"
              disabled={!selectedKeywords.length}
              onClick={() => selectCandidates([])}
            >
              清空选择
            </Button>
          </Space>
          <Typography.Text>已选 {addableSelected.length} 个</Typography.Text>
        </div>
        <List
          bordered
          dataSource={cache?.keywords ?? []}
          locale={{ emptyText: '本次没有生成可用的候选关键词' }}
          renderItem={(candidate) => {
            const added = existingKeywords.has(normalizeKeyword(candidate.keyword));
            return (
              <List.Item>
                <div className={styles.candidate}>
                  <div className={styles.candidateTitle}>
                    <Checkbox
                      aria-label={`选择关键词：${candidate.keyword}`}
                      checked={selectedKeywords.includes(candidate.keyword)}
                      disabled={added}
                      onChange={(event) =>
                        selectCandidates(
                          event.target.checked
                            ? [...new Set([...selectedKeywords, candidate.keyword])]
                            : selectedKeywords.filter((keyword) => keyword !== candidate.keyword),
                        )
                      }
                    >
                      <Typography.Text strong>{candidate.keyword}</Typography.Text>
                    </Checkbox>
                    <Space size={4}>
                      {candidate.category ? <Tag color="blue">{candidate.category}</Tag> : null}
                      {added ? <Tag color="success">已添加</Tag> : null}
                    </Space>
                  </div>
                  {candidate.reason ? (
                    <Typography.Text type="secondary" className={styles.candidateDescription}>
                      {candidate.reason}
                    </Typography.Text>
                  ) : null}
                </div>
              </List.Item>
            );
          }}
        />
      </div>
    );
    footer = (
      <div className={styles.footer}>
        <Button
          disabled={adding}
          onClick={() => {
            setStep('configure');
            setError(undefined);
          }}
        >
          调整参考来源
        </Button>
        <Button disabled={adding} onClick={confirmRegenerate}>重新生成</Button>
        <Button
          type="primary"
          loading={adding}
          disabled={!addableSelected.length}
          onClick={() => void addSelected()}
        >
          添加所选 {addableSelected.length ? `${addableSelected.length} 个` : ''}
        </Button>
      </div>
    );
  }

  return (
    <Modal
      title="AI 生成候选关键词"
      open={open}
      width={720}
      footer={footer}
      mask={{ closable: !generating }}
      closable={!generating}
      onCancel={close}
      destroyOnHidden
    >
      {content}
    </Modal>
  );
}
