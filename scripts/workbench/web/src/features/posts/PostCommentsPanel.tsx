import { HeartOutlined, UserOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { Link } from '@umijs/max';
import { Alert, Avatar, Button, Empty, List, Pagination, Space, Tag, Typography } from 'antd';
import { useState } from 'react';
import { apiService } from '@/services/api';
import { queryKeys } from '@/services/queryKeys';
import type { Post, PostComment } from '@/types';
import { activeTaskStatuses, formatDate, formatNumber, taskStatusLabels } from '@/utils/format';
import PostCommentCollectionAction, {
  PostCommentQuickCollectionAction,
} from './PostCommentCollectionAction';

function CommentBody({ comment, reply = false }: { comment: PostComment; reply?: boolean }) {
  return (
    <div style={reply ? { marginInlineStart: 44, paddingBlock: 8 } : undefined}>
      <Space align="start">
        <Avatar
          src={comment.author_avatar_url || undefined}
          icon={<UserOutlined />}
          size={reply ? 28 : 36}
        />
        <div>
          <Space size="small" wrap>
            <Typography.Text strong>{comment.author_name || '未知用户'}</Typography.Text>
            {reply ? <Tag>{comment.is_reply_preview ? '回复预览' : '回复'}</Tag> : null}
            {comment.ip_location ? (
              <Typography.Text type="secondary">{comment.ip_location}</Typography.Text>
            ) : null}
          </Space>
          <Typography.Paragraph style={{ marginBlock: 4 }}>
            {comment.content || '（无文本）'}
          </Typography.Paragraph>
          <Space size="middle">
            <Typography.Text type="secondary">{formatDate(comment.published_at)}</Typography.Text>
            <Typography.Text type="secondary">
              <HeartOutlined /> {formatNumber(comment.likes_count)}
            </Typography.Text>
            {!reply && comment.platform_reply_count ? (
              <Typography.Text type="secondary">
                平台显示 {formatNumber(comment.platform_reply_count)} 条回复
              </Typography.Text>
            ) : null}
          </Space>
        </div>
      </Space>
    </div>
  );
}

export default function PostCommentsPanel({ post }: { post: Post }) {
  const [page, setPage] = useState(1);
  const pageSize = 20;
  const comments = useQuery({
    queryKey: queryKeys.postComments(post.id, page, pageSize),
    queryFn: ({ signal }) => apiService.postComments(post.id, page, pageSize, signal),
    refetchInterval: (query) => {
      const status = query.state.data?.summary.active_task?.status;
      return status && activeTaskStatuses.has(status) ? 1_500 : false;
    },
  });
  if (comments.isError) {
    return (
      <Alert
        showIcon
        type="error"
        title="评论数据加载失败"
        description={comments.error.message}
        action={<Button onClick={() => comments.refetch()}>重试</Button>}
      />
    );
  }
  const data = comments.data;
  const summary = data?.summary;
  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
      <Space wrap>
        <PostCommentCollectionAction
          post={post}
          buttonType="primary"
          checkpoint={summary?.checkpoint}
        />
        <PostCommentQuickCollectionAction
          post={post}
          checkpoint={summary?.checkpoint}
          disabled={Boolean(summary?.active_task)}
        />
        <Typography.Text type="secondary">
          累计保存 {formatNumber(summary?.root_comment_count ?? 0)} 条一级评论、
          {formatNumber((summary?.reply_preview_count ?? 0) + (summary?.reply_count ?? 0))} 条回复
        </Typography.Text>
        {summary?.latest_task ? (
          <Link to={`/tasks/${summary.latest_task.id}`}>
            最近任务 · {taskStatusLabels[summary.latest_task.status]}
          </Link>
        ) : null}
        {summary?.last_comments_fetched_at ? (
          <Typography.Text type="secondary">
            更新于 {formatDate(summary.last_comments_fetched_at)}
          </Typography.Text>
        ) : null}
      </Space>
      {summary?.checkpoint ? (
        <Alert
          showIcon
          type={summary.checkpoint.status === 'invalid' ? 'warning' : 'info'}
          title={
            summary.checkpoint.status === 'active'
              ? `已续传 ${summary.checkpoint.completed_pages} 页，还有更多评论`
              : summary.checkpoint.status === 'exhausted'
                ? `已续传 ${summary.checkpoint.completed_pages} 页，已到平台当前末页`
                : '续传位置已失效'
          }
          description={
            summary.checkpoint.status === 'invalid'
              ? '请使用“重新更新”从首页重建续传位置，已保存的评论不会删除。'
              : `上次保存续传位置：${formatDate(summary.checkpoint.captured_at)}`
          }
        />
      ) : null}
      {summary?.active_task ? (
        <Alert
          showIcon
          type="info"
          title="评论采集正在进行"
          description={`进度 ${summary.active_task.progress_current}/${summary.active_task.progress_total} 页，数据会自动刷新。`}
        />
      ) : null}
      <section aria-label="评论列表" className="post-comments-scroll">
        {!comments.isPending && !data?.items.length ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未抓取评论">
            <PostCommentCollectionAction post={post} checkpoint={summary?.checkpoint} />
          </Empty>
        ) : (
          <List
            loading={comments.isPending}
            dataSource={data?.items ?? []}
            renderItem={(comment) => (
              <List.Item key={comment.comment_id} style={{ display: 'block' }}>
                <CommentBody comment={comment} />
                {comment.reply_previews.map((reply) => (
                  <CommentBody key={reply.comment_id} comment={reply} reply />
                ))}
              </List.Item>
            )}
          />
        )}
        {(data?.total ?? 0) > pageSize ? (
          <Pagination
            current={page}
            pageSize={pageSize}
            total={data?.total ?? 0}
            showSizeChanger={false}
            onChange={setPage}
          />
        ) : null}
      </section>
    </Space>
  );
}
