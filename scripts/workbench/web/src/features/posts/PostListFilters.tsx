import { FilterOutlined } from '@ant-design/icons';
import { Badge, Button, Input, Popover, Select, Space, Tag, Typography } from 'antd';
import type { ReactNode } from 'react';
import { useState } from 'react';
import type { MediaStorageFilter, MediaStorageStatus, OcrStatus } from '@/types';

export interface PostListFilterState {
  query: string;
  type: 'all' | 'image' | 'video';
  detail: 'all' | 'preview' | 'detailed';
  ocr: 'all' | OcrStatus;
  vision: 'all' | 'yes' | 'no';
}

export const DEFAULT_POST_LIST_FILTERS: PostListFilterState = {
  query: '',
  type: 'all',
  detail: 'all',
  ocr: 'all',
  vision: 'all',
};

export interface AdditionalPostListFilter {
  key: string;
  label: ReactNode;
  ariaLabel: string;
  value: string;
  defaultValue?: string;
  options: Array<{ value: string; label: ReactNode }>;
  onChange: (value: string) => void;
}

interface FilterablePost {
  title?: string;
  content?: string;
  author_name?: string;
  external_author_id?: string;
  note_id?: string;
  sources?: string;
  note_type?: string;
  detail_level?: string;
  has_ocr_result?: number | null;
  ocr_status?: OcrStatus;
  has_vision_result?: number | null;
  media_storage_status?: MediaStorageStatus;
}

export function filterPostsByMediaStorage<T extends FilterablePost>(
  posts: T[],
  mediaStorage: MediaStorageFilter,
): T[] {
  if (mediaStorage === 'all') return posts;
  return posts.filter((post) => post.media_storage_status === mediaStorage);
}

export function filterPostList<T extends FilterablePost>(
  posts: T[],
  filters: PostListFilterState,
): T[] {
  const normalized = filters.query.trim().toLocaleLowerCase('zh-CN');
  return posts.filter((post) => {
    const matchesQuery =
      !normalized ||
      [
        post.title,
        post.content,
        post.author_name,
        post.external_author_id,
        post.note_id,
        post.sources,
      ].some((value) => String(value || '').toLocaleLowerCase('zh-CN').includes(normalized));
    const matchesType =
      filters.type === 'all' ||
      (filters.type === 'image' ? post.note_type !== 'video' : post.note_type === 'video');
    const hasDetails = Boolean(post.detail_level && post.detail_level !== 'card');
    const matchesDetail =
      filters.detail === 'all' || hasDetails === (filters.detail === 'detailed');
    const ocrStatus = post.ocr_status || (Number(post.has_ocr_result) ? 'completed' : 'other');
    const matchesOcr = filters.ocr === 'all' || ocrStatus === filters.ocr;
    const hasVision = Boolean(Number(post.has_vision_result));
    const matchesVision =
      filters.vision === 'all' || hasVision === (filters.vision === 'yes');
    return matchesQuery && matchesType && matchesDetail && matchesOcr && matchesVision;
  });
}

export function PostOcrStatus({
  value,
  status,
}: {
  value?: number | null;
  status?: OcrStatus;
}) {
  const resolved = status || (Number(value) ? 'completed' : 'other');
  if (resolved === 'completed') return <Tag color="success">OCR 已完成</Tag>;
  if (resolved === 'pending') return <Tag color="processing">待执行 OCR</Tag>;
  return <Tag>其他</Tag>;
}

export function PostVisionStatus({ value }: { value?: number | null }) {
  return Number(value) ? <Tag color="success">已有图片理解</Tag> : <Tag>未做图片理解</Tag>;
}

export function PostDetailStatus({ value }: { value?: string }) {
  return value && value !== 'card' ? <Tag color="blue">已有详细信息</Tag> : <Tag>仅预览信息</Tag>;
}

export default function PostListFilters({
  value,
  onChange,
  additionalFilters = [],
}: {
  value: PostListFilterState;
  onChange: (next: PostListFilterState) => void;
  additionalFilters?: AdditionalPostListFilter[];
}) {
  const [open, setOpen] = useState(false);
  const [advancedDraft, setAdvancedDraft] = useState<Pick<PostListFilterState, 'vision'>>({
    vision: value.vision,
  });
  const [additionalDraft, setAdditionalDraft] = useState<Record<string, string>>({});
  const handleOpenChange = (next: boolean) => {
    if (next) {
      setAdvancedDraft({ vision: value.vision });
      setAdditionalDraft(
        Object.fromEntries(additionalFilters.map((filter) => [filter.key, filter.value])),
      );
    }
    setOpen(next);
  };
  const activeAdvancedCount = [
    value.vision !== 'all',
    ...additionalFilters.map(
      (filter) => filter.value !== (filter.defaultValue ?? 'all'),
    ),
  ].filter(Boolean).length;
  const resetAdvanced = () => {
    onChange({ ...value, vision: 'all' });
    additionalFilters.forEach((filter) => {
      filter.onChange(filter.defaultValue ?? 'all');
    });
    setOpen(false);
  };
  const applyAdvanced = () => {
    onChange({ ...value, ...advancedDraft });
    additionalFilters.forEach((filter) => {
      filter.onChange(additionalDraft[filter.key] ?? filter.value);
    });
    setOpen(false);
  };
  return (
    <Space wrap size={8}>
      <Input.Search
        allowClear
        value={value.query}
        onChange={(event) => onChange({ ...value, query: event.target.value })}
        placeholder="搜索帖子"
        aria-label="搜索标题、正文、作者、来源或帖子 ID"
        style={{ width: 240 }}
      />
      <Select
        aria-label="按帖子类型筛选"
        value={value.type}
        onChange={(type) => onChange({ ...value, type })}
        style={{ width: 112 }}
        options={[
          { value: 'all', label: '全部类型' },
          { value: 'image', label: '图文' },
          { value: 'video', label: '视频' },
        ]}
      />
      <Select
        aria-label="按帖子信息完整度筛选"
        value={value.detail}
        onChange={(detail) => onChange({ ...value, detail })}
        style={{ width: 144 }}
        options={[
          { value: 'all', label: '全部信息状态' },
          { value: 'preview', label: '仅预览信息' },
          { value: 'detailed', label: '已有详细信息' },
        ]}
      />
      <Select
        aria-label="按 OCR 识图状态筛选"
        value={value.ocr}
        onChange={(ocr) => onChange({ ...value, ocr })}
        style={{ width: 144 }}
        options={[
          { value: 'all', label: '全部 OCR 状态' },
          { value: 'pending', label: '待执行 OCR' },
          { value: 'completed', label: 'OCR 已完成' },
          { value: 'other', label: '其他' },
        ]}
      />
      <Popover
        title="更多筛选"
        trigger="click"
        placement="bottomRight"
        open={open}
        onOpenChange={handleOpenChange}
        content={(
          <div className="post-advanced-filters">
            <div className="post-advanced-filter-field">
              <Typography.Text type="secondary">图片理解状态</Typography.Text>
              <Select
                aria-label="按图片理解状态筛选"
                value={advancedDraft.vision}
                onChange={(vision) => setAdvancedDraft((current) => ({ ...current, vision }))}
                options={[
                  { value: 'all', label: '全部图片理解状态' },
                  { value: 'yes', label: '已有图片理解' },
                  { value: 'no', label: '未做图片理解' },
                ]}
              />
            </div>
            {additionalFilters.map((filter) => (
              <div className="post-advanced-filter-field" key={filter.key}>
                <Typography.Text type="secondary">{filter.label}</Typography.Text>
                <Select
                  aria-label={filter.ariaLabel}
                  value={additionalDraft[filter.key] ?? filter.value}
                  onChange={(next) =>
                    setAdditionalDraft((current) => ({ ...current, [filter.key]: next }))
                  }
                  options={filter.options}
                />
              </div>
            ))}
            <div className="post-advanced-filter-actions">
              <Button aria-label="重置" onClick={resetAdvanced}>重置</Button>
              <Button aria-label="确定" type="primary" onClick={applyAdvanced}>确定</Button>
            </div>
          </div>
        )}
      >
        <Badge count={activeAdvancedCount} size="small" offset={[-4, 2]}>
          <Button icon={<FilterOutlined />}>更多筛选</Button>
        </Badge>
      </Popover>
    </Space>
  );
}
