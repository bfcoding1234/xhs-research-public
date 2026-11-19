import {
  HeartOutlined,
  LeftOutlined,
  MessageOutlined,
  RightOutlined,
  StarOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { Link } from '@umijs/max';
import { Button, Descriptions, Empty, Image, Space, Tabs, Tag, Typography } from 'antd';
import { useMemo, useState } from 'react';
import type { Post } from '@/types';
import { formatDate, formatNumber, formatPublishDate } from '@/utils/format';
import PostMediaPreview, { mediaSourceColor, mediaSourceLabel } from './PostMediaPreview';
import PostCommentsPanel from './PostCommentsPanel';
import VisionAnalysisSection from './VisionAnalysisSection';

const { Paragraph, Text, Title } = Typography;

const detailLevelLabels: Record<string, string> = {
  media: '详情与媒体',
  detail: '帖子详情',
  card: '列表卡片',
};

function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value: number | null }) {
  return (
    <div className="post-detail-metric">
      <span className="post-detail-metric-icon">{icon}</span>
      <span>
        <strong>{formatNumber(value)}</strong>
        {label}
      </span>
    </div>
  );
}

function deduplicateMedia(media: Post['media']): NonNullable<Post['media']> {
  const seen = new Set<string>();
  return (media || []).filter((item) => {
    // A cover can be recorded both as the cover asset and as the first content asset.
    // Prefer the original source URL because the two local copies have different paths.
    const key = item.original_url || item.local_url || item.local_path || String(item.id);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function OcrText({ text }: { text: string }) {
  const occurrences = new Map<string, number>();
  const lines = text
    .split(/\r?\n\s*\r?\n/)
    .map((paragraph) =>
      paragraph
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean)
        .reduce((combined, line) => {
          if (!combined) return line;
          const previousCharacter = combined.at(-1) || '';
          const nextCharacter = line[0] || '';
          const separator = /[a-zA-Z0-9][a-zA-Z0-9]/.test(`${previousCharacter}${nextCharacter}`)
            ? ' '
            : '';
          return `${combined}${separator}${line}`;
        }, '')
        .trim(),
    )
    .filter(Boolean)
    .map((paragraph) => {
      const occurrence = occurrences.get(paragraph) || 0;
      occurrences.set(paragraph, occurrence + 1);
      return { key: `${paragraph}-${occurrence}`, value: paragraph };
    });
  if (!lines.length) return <Text type="secondary">没有识别到文本</Text>;
  return (
    <div className="post-detail-ocr-copy">
      {lines.map((line) => (
        <p key={line.key}>{line.value}</p>
      ))}
    </div>
  );
}

export default function PostDetailContent({
  post,
  mode,
}: {
  post: Post;
  mode: 'page' | 'drawer';
}) {
  const media = useMemo(() => deduplicateMedia(post.media), [post.media]);
  const [requestedMediaIndex, setRequestedMediaIndex] = useState(0);
  const activeMediaIndex = Math.min(requestedMediaIndex, Math.max(0, media.length - 1));
  const activeMedia = media[activeMediaIndex];
  const canSwitchMedia = media.length > 1;
  const moveMedia = (offset: number) => {
    if (!canSwitchMedia) return;
    setRequestedMediaIndex((current) => (current + offset + media.length) % media.length);
  };
  const facts = useMemo(
    () => [
      { key: 'publish', label: '发布时间', children: formatPublishDate(post.publish_date) },
      { key: 'updated', label: '最近更新', children: formatDate(post.updated_at) },
      { key: 'note', label: '帖子 ID', children: <Text copyable>{post.note_id}</Text> },
      ...(mode === 'drawer'
        ? [
            {
              key: 'source',
              label: '采集来源',
              children: <Text copyable={Boolean(post.sources)}>{post.sources || '—'}</Text>,
            },
          ]
        : [
            {
              key: 'projects',
              label: '关联项目',
              children: post.projects?.length ? (
                <Space wrap size={[4, 4]}>
                  {post.projects.map((project) => (
                    <Link key={project.id} to={`/projects/${project.id}`}>
                      <Tag color="blue">{project.name}</Tag>
                    </Link>
                  ))}
                </Space>
              ) : (
                '暂未关联项目'
              ),
            },
          ]),
    ],
    [mode, post],
  );

  const mediaStage = activeMedia ? (
    <PostMediaPreview
      media={activeMedia}
      alt={`${post.title || post.note_id || '帖子'} 媒体 ${activeMediaIndex + 1}`}
    />
  ) : post.media_url || post.cover_url ? (
    <Image src={post.media_url || post.cover_url} alt={post.title || '帖子封面'} />
  ) : (
    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有帖子封面" />
  );

  return (
    <article className="post-detail-workspace" data-testid="post-detail-layout">
      <header className="post-detail-summary">
        <div className="post-detail-summary-copy">
          <Space size={[6, 6]} wrap>
            <Tag color={post.note_type === 'video' ? 'purple' : 'blue'}>
              {post.note_type === 'video' ? '视频' : '图文'}
            </Tag>
            {post.popularity_level ? <Tag color="volcano">{post.popularity_level}</Tag> : null}
            <Tag>{detailLevelLabels[post.detail_level] || post.detail_level || '未知层级'}</Tag>
          </Space>
          <Title level={3}>{post.title || post.note_id}</Title>
          <div className="post-detail-author">
            <UserOutlined />
            {mode === 'page' && post.author_id ? (
              <Link to={`/authors/${post.author_id}`}>{post.author_name || post.external_author_id}</Link>
            ) : (
              <Text>{post.author_name || '未知作者'}</Text>
            )}
            <Text type="secondary">· {formatPublishDate(post.publish_date)}</Text>
          </div>
        </div>
        <section className="post-detail-metrics" aria-label="互动数据">
          <Metric icon={<HeartOutlined />} label="点赞" value={post.likes_count} />
          <Metric icon={<StarOutlined />} label="收藏" value={post.favorites_count} />
          <Metric icon={<MessageOutlined />} label="评论" value={post.comments_count} />
        </section>
      </header>

      <div className="post-detail-workbench-grid">
        <aside
          aria-keyshortcuts={canSwitchMedia ? 'ArrowLeft ArrowRight' : undefined}
          aria-label="帖子媒体"
          className="post-detail-media-browser"
          onKeyDown={(event) => {
            if (event.key === 'ArrowLeft') {
              event.preventDefault();
              moveMedia(-1);
            }
            if (event.key === 'ArrowRight') {
              event.preventDefault();
              moveMedia(1);
            }
          }}
          tabIndex={canSwitchMedia ? 0 : undefined}
        >
          <div className="post-detail-cover-stage">{mediaStage}</div>
          {canSwitchMedia ? (
            <div className="post-detail-media-navigation">
              <Button
                aria-label="上一张"
                icon={<LeftOutlined />}
                onClick={() => moveMedia(-1)}
                size="small"
                type="text"
              />
              <Text aria-live="polite">{activeMediaIndex + 1} / {media.length}</Text>
              <Button
                aria-label="下一张"
                icon={<RightOutlined />}
                onClick={() => moveMedia(1)}
                size="small"
                type="text"
              />
            </div>
          ) : null}
          {canSwitchMedia ? (
            <nav className="post-detail-media-thumbnails" aria-label="选择媒体">
              {media.map((item, index) => (
                <button
                  aria-label={`查看媒体 ${index + 1}`}
                  aria-current={index === activeMediaIndex ? 'true' : undefined}
                  aria-pressed={index === activeMediaIndex}
                  className={index === activeMediaIndex ? 'is-active' : ''}
                  key={item.id}
                  onClick={() => setRequestedMediaIndex(index)}
                  type="button"
                >
                  <Image
                    alt={`媒体 ${index + 1} 缩略图`}
                    fallback=""
                    preview={false}
                    src={item.local_url || item.original_url}
                  />
                </button>
              ))}
            </nav>
          ) : null}
          {activeMedia ? (
            <div className="post-detail-media-status">
              <Text>媒体 {activeMediaIndex + 1}</Text>
              <Tag color={mediaSourceColor(activeMedia)}>{mediaSourceLabel(activeMedia)}</Tag>
            </div>
          ) : null}
        </aside>

        <section className="post-detail-content-panel">
          <Tabs
            items={[
              {
                key: 'content',
                label: '内容',
                children: (
                  <div className="post-detail-content-overview">
                    <Descriptions column={{ xs: 1, sm: 2 }} items={facts} size="small" />
                    <div className="post-detail-content-divider" />
                    {post.content ? (
                      <Paragraph className="post-detail-copy" copyable>
                        {post.content}
                      </Paragraph>
                    ) : (
                      <Text type="secondary">当前保存的是列表卡片数据，尚未读取正文详情。</Text>
                    )}
                  </div>
                ),
              },
              {
                key: 'comments',
                label: `评论${post.last_comments_fetched_at ? ' · 已抓取' : ''}`,
                children: <PostCommentsPanel post={post} />,
              },
              {
                key: 'ocr',
                label: `OCR${media.length ? ` ${media.length}` : ''}`,
                children: activeMedia ? (
                  <div className="post-detail-ocr-panel">
                    <Space size="small" wrap>
                      <Tag color={mediaSourceColor(activeMedia)}>{mediaSourceLabel(activeMedia)}</Tag>
                      <Text type="secondary">
                        媒体 {activeMediaIndex + 1} · {activeMedia.ocr_engine || '未知 OCR 引擎'}
                      </Text>
                    </Space>
                    {activeMedia.ocr_text ? (
                      <div className="post-detail-ocr-content">
                        <Text copyable={{ text: activeMedia.ocr_text }}>复制全文</Text>
                        <OcrText text={activeMedia.ocr_text} />
                      </div>
                    ) : (
                      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有识别到文本" />
                    )}
                  </div>
                ) : (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有媒体或 OCR 结果" />
                ),
              },
              {
                key: 'vision',
                label: `图片理解${post.vision?.length ? ` ${post.vision.length}` : ''}`,
                children: <VisionAnalysisSection analyses={post.vision} compact />,
              },
            ]}
          />
        </section>
      </div>
    </article>
  );
}
