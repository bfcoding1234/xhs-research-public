import { DownOutlined, SyncOutlined } from '@ant-design/icons';
import { history } from '@umijs/max';
import type { MenuProps } from 'antd';
import { App, Button, Dropdown, Tooltip } from 'antd';
import { useMemo, useState } from 'react';
import type { Author } from '@/types';
import AuthorBatchUpdateModal from './AuthorBatchUpdateModal';
import type { AuthorBatchUpdateMode } from './AuthorBatchUpdateModal';
import type { AuthorBatchResult } from './authorBatchUpdate';
import { MAX_AUTHOR_BATCH_SIZE } from './authorBatchUpdate';

export default function AuthorBatchUpdateControl({
  authors,
  selectedIds,
  onSelectionChange,
}: {
  authors: Author[];
  selectedIds: number[];
  onSelectionChange: (ids: number[]) => void;
}) {
  const [mode, setMode] = useState<AuthorBatchUpdateMode | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const { message, notification } = App.useApp();
  const selectedAuthors = useMemo(() => {
    const authorsById = new Map(authors.map((author) => [author.id, author]));
    return selectedIds
      .map((id) => authorsById.get(id))
      .filter((author): author is Author => Boolean(author));
  }, [authors, selectedIds]);

  const unavailableReason =
    selectedIds.length === 0
      ? '请先选择作者'
      : selectedIds.length > MAX_AUTHOR_BATCH_SIZE
        ? `单次最多批量更新 ${MAX_AUTHOR_BATCH_SIZE} 位作者，请分批操作`
        : undefined;
  const menuItems: MenuProps['items'] = [
    { key: 'basic_info', label: '更新作者信息' },
    { key: 'posts', label: '更新帖子信息' },
  ];

  const open = (nextMode: AuthorBatchUpdateMode) => {
    if (selectedIds.length === 0) return;
    if (selectedIds.length > MAX_AUTHOR_BATCH_SIZE) {
      message.warning(`单次最多批量更新 ${MAX_AUTHOR_BATCH_SIZE} 位作者，请分批操作`);
      return;
    }
    if (selectedAuthors.length !== selectedIds.length) {
      message.error('部分已选作者已不在当前列表中，请刷新后重新选择');
      return;
    }
    setMode(nextMode);
  };

  const handleComplete = (result: AuthorBatchResult) => {
    onSelectionChange(result.failures.map(({ author }) => author.id));
    const viewTasksButton = result.successes.length ? (
      <Button type="link" size="small" onClick={() => history.push('/tasks')}>
        查看任务列表
      </Button>
    ) : undefined;

    if (result.failures.length === 0) {
      notification.success({
        message: '批量任务已创建',
        description: `已创建 ${result.successes.length} 个独立更新任务，数据将在任务执行后更新。`,
        actions: viewTasksButton,
      });
      return;
    }

    const failureText = result.failures
      .slice(0, 3)
      .map(({ author, message: reason }) => `${author.display_name || author.author_id}：${reason}`)
      .join('；');
    const remainingText =
      result.failures.length > 3 ? `；另有 ${result.failures.length - 3} 位失败` : '';
    const description = `${failureText}${remainingText}。失败作者已保持选中。`;

    if (result.successes.length) {
      notification.warning({
        message: `已创建 ${result.successes.length} 个任务，${result.failures.length} 个失败`,
        description,
        actions: viewTasksButton,
      });
    } else {
      notification.error({ message: '未能创建批量更新任务', description });
    }
  };

  return (
    <>
      <span className="author-batch-update-control">
        <Tooltip title={unavailableReason}>
          <span>
            <Dropdown
              disabled={Boolean(unavailableReason) || submitting}
              menu={{
                items: menuItems,
                onClick: ({ key }) => open(key === 'basic_info' ? 'basic_info' : 'posts'),
              }}
              trigger={['click']}
            >
              <Button
                aria-label={selectedIds.length ? `批量更新，已选 ${selectedIds.length} 位` : '批量更新'}
                icon={<SyncOutlined />}
                loading={submitting}
                disabled={Boolean(unavailableReason)}
              >
                批量更新 <DownOutlined />
              </Button>
            </Dropdown>
          </span>
        </Tooltip>
      </span>
      {mode ? (
        <AuthorBatchUpdateModal
          open
          mode={mode}
          authors={selectedAuthors}
          onClose={() => setMode(null)}
          onComplete={handleComplete}
          onSubmittingChange={setSubmitting}
        />
      ) : null}
    </>
  );
}
