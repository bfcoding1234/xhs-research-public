import {
  DeleteOutlined,
  FilterOutlined,
  LinkOutlined,
  SearchOutlined,
  SyncOutlined,
} from '@ant-design/icons';
import type { ProColumns } from '@ant-design/pro-components';
import { ProTable } from '@ant-design/pro-components';
import { Badge, Button, Input, Popover, Select, Space, Tag, Typography } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import AuthorBatchUpdateControl from '@/features/authors/AuthorBatchUpdateControl';
import AuthorListActions from '@/features/authors/AuthorListActions';
import {
  DEFAULT_AUTHOR_VIEW_MODE,
  AuthorListHeader,
  AuthorToolbarActions,
  createAuthorTableViewRender,
  type AuthorCardSort,
  type AuthorViewMode,
} from '@/features/authors/AuthorView';
import {
  tableSortFromChange,
  tableSortOrder,
  useListSort,
} from '@/features/preferences/listSortPreferences';
import { TABLE_COLUMN_PREFERENCES } from '@/features/preferences/tableColumnPreferences';
import type { Author } from '@/types';
import { createPersistentRowSelection } from '@/features/selection/persistentRowSelection';
import { sortAuthorsByFollowersDesc } from '@/utils/authors';
import { formatDate, formatNumber } from '@/utils/format';

export type ProjectAuthorSource = 'task_added' | 'manual' | 'keyword_post_author' | 'all';

const sourceLabels: Record<Exclude<ProjectAuthorSource, 'all'>, string> = {
  task_added: '任务主动添加',
  manual: '手动关联',
  keyword_post_author: '关键词帖子作者',
};

const relationSources: Record<Exclude<ProjectAuthorSource, 'all'>, Set<string>> = {
  task_added: new Set([
    'task_added',
    'research_source',
    'author_update',
    'keyword_discovered',
    'discovered',
    'benchmark',
    'keyword',
  ]),
  manual: new Set(['manual', 'post_author']),
  keyword_post_author: new Set(['keyword_post_author']),
};

const PROJECT_AUTHOR_TABLE_SORTS = [
  'project_posts:asc',
  'project_posts:desc',
  'followers:asc',
  'followers:desc',
  'likes:asc',
  'likes:desc',
  'updated:asc',
  'updated:desc',
] as const;
const AUTHOR_CARD_SORTS: readonly AuthorCardSort[] = [
  'followers_desc',
  'followers_asc',
  'likes_desc',
  'posts_desc',
  'updated_desc',
  'name_asc',
];

export function projectAuthorSources(author: Pick<Author, 'relation_type'>) {
  const relations = String(author.relation_type || '')
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean);
  return (Object.keys(relationSources) as Array<Exclude<ProjectAuthorSource, 'all'>>).filter(
    (source) => relations.some((relation) => relationSources[source].has(relation)),
  );
}

export default function ProjectAuthorsTable({
  authors,
  onSelect,
  onLink,
  onUnlink,
  onBulkUpdate,
}: {
  authors: Author[];
  onSelect: (id: number) => void;
  onLink: () => void;
  onUnlink: (ids: number[]) => void;
  onBulkUpdate?: () => void;
}) {
  const [view, setView] = useState<AuthorViewMode>(DEFAULT_AUTHOR_VIEW_MODE);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [query, setQuery] = useState('');
  const [source, setSource] = useState<ProjectAuthorSource>('all');
  const [sourceDraft, setSourceDraft] = useState<ProjectAuthorSource>('all');
  const [sourceFilterOpen, setSourceFilterOpen] = useState(false);
  const [tableSort, setTableSort] = useListSort(
    'authors.project.table',
    PROJECT_AUTHOR_TABLE_SORTS,
    'followers:desc',
  );
  const [cardSort, setCardSort] = useListSort<AuthorCardSort>(
    'authors.project.card',
    AUTHOR_CARD_SORTS,
    'followers_desc',
  );
  const data = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase('zh-CN');
    return sortAuthorsByFollowersDesc(
      authors.filter(
        (author) =>
          (source === 'all' || projectAuthorSources(author).includes(source)) &&
          (!normalized ||
            [author.display_name, author.author_id, author.xhs_id, author.bio].some((value) =>
              String(value || '')
                .toLocaleLowerCase('zh-CN')
                .includes(normalized),
            )),
      ),
    );
  }, [authors, query, source]);
  useEffect(() => {
    const validIds = new Set(authors.map((author) => author.id));
    setSelectedIds((current) => current.filter((id) => validIds.has(id)));
  }, [authors]);
  const rowSelection = createPersistentRowSelection<Author>(selectedIds, setSelectedIds);
  const columns: ProColumns<Author>[] = [
    {
      title: '作者',
      dataIndex: 'display_name',
      width: 260,
      fixed: 'left',
      render: (_, row) => (
        <Space orientation="vertical" size={0}>
          <Button type="link" style={{ padding: 0 }} onClick={() => onSelect(row.id)}>
            {row.display_name || row.author_id}
          </Button>
          <Typography.Text type="secondary" className="mono">
            {row.author_id}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: '关系',
      dataIndex: 'relation_type',
      width: 180,
      render: (_, row) =>
        projectAuthorSources(row).length
          ? projectAuthorSources(row).map((value) => (
              <Tag color={value === 'task_added' ? 'blue' : undefined} key={value}>
                {sourceLabels[value]}
              </Tag>
            ))
          : '—',
    },
    {
      title: 'IP 属地',
      dataIndex: 'ip_location',
      width: 120,
      renderText: (value: string) => value || '—',
    },
    {
      title: '项目帖子',
      dataIndex: 'project_post_count',
      width: 110,
      align: 'right',
      renderText: formatNumber,
      sorter: (left, right) =>
        Number(left.project_post_count || 0) - Number(right.project_post_count || 0),
      key: 'project_posts',
      sortOrder: tableSortOrder(tableSort, 'project_posts'),
    },
    {
      title: '粉丝',
      dataIndex: 'followers_count',
      width: 120,
      align: 'right',
      renderText: formatNumber,
      sorter: (left, right) =>
        Number(left.followers_count || 0) - Number(right.followers_count || 0),
      key: 'followers',
      sortOrder: tableSortOrder(tableSort, 'followers'),
    },
    {
      title: '获赞与收藏',
      dataIndex: 'likes_collections_count',
      width: 140,
      align: 'right',
      renderText: formatNumber,
      sorter: (left, right) =>
        Number(left.likes_collections_count || 0) - Number(right.likes_collections_count || 0),
      key: 'likes',
      sortOrder: tableSortOrder(tableSort, 'likes'),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 180,
      renderText: (value: string) => formatDate(value),
      sorter: (left, right) => Date.parse(left.updated_at) - Date.parse(right.updated_at),
      key: 'updated',
      sortOrder: tableSortOrder(tableSort, 'updated'),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 160,
      fixed: 'right',
      render: (_, row) => <AuthorListActions author={row} onDetail={() => onSelect(row.id)} />,
    },
  ];
  const batchActions = (
    <AuthorToolbarActions
      selectedCount={selectedIds.length}
      onClearSelection={() => setSelectedIds([])}
    >
      <AuthorBatchUpdateControl
        authors={authors}
        selectedIds={selectedIds}
        onSelectionChange={setSelectedIds}
      />
      <Button key="link" type="primary" icon={<LinkOutlined />} onClick={onLink}>
        关联作者
      </Button>
      <Button
        key="unlink"
        danger
        icon={<DeleteOutlined />}
        disabled={selectedIds.length === 0}
        aria-label={selectedIds.length ? `取消关联，已选 ${selectedIds.length} 位` : '取消关联'}
        onClick={() => onUnlink(selectedIds)}
      >
        取消关联
      </Button>
    </AuthorToolbarActions>
  );
  return (
    <div className="author-list-section">
      <AuthorListHeader
        title={`项目作者（${data.length}/${authors.length}）`}
        view={view}
        onViewChange={setView}
        showViewLabel
        query={(
          <Space wrap size={8}>
            <Input
              allowClear
              prefix={<SearchOutlined />}
              value={query}
              aria-label="搜索项目作者名、作者 ID、小红书号或简介"
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索作者"
            />
            <Popover
              title="更多筛选"
              trigger="click"
              placement="bottomRight"
              open={sourceFilterOpen}
              onOpenChange={(next) => {
                if (next) setSourceDraft(source);
                setSourceFilterOpen(next);
              }}
              content={(
                <div className="author-advanced-filters">
                  <div className="author-advanced-filter-field">
                    <Typography.Text type="secondary">作者来源</Typography.Text>
                    <Select<ProjectAuthorSource>
                      aria-label="项目作者来源"
                      value={sourceDraft}
                      onChange={setSourceDraft}
                      options={[
                        { value: 'all', label: '全部来源' },
                        { value: 'task_added', label: '任务主动添加' },
                        { value: 'manual', label: '手动关联' },
                        { value: 'keyword_post_author', label: '关键词帖子作者' },
                      ]}
                    />
                  </div>
                  <div className="author-advanced-filter-actions">
                    <Button
                      aria-label="重置"
                      onClick={() => {
                        setSource('all');
                        setSourceDraft('all');
                        setSourceFilterOpen(false);
                      }}
                    >
                      重置
                    </Button>
                    <Button
                      aria-label="确定"
                      type="primary"
                      onClick={() => {
                        setSource(sourceDraft);
                        setSourceFilterOpen(false);
                      }}
                    >
                      确定
                    </Button>
                  </div>
                </div>
              )}
            >
              <Badge count={source === 'all' ? 0 : 1} size="small" offset={[-4, 2]}>
                <Button icon={<FilterOutlined />}>更多筛选</Button>
              </Badge>
            </Popover>
          </Space>
        )}
        actions={
          onBulkUpdate ? (
            <Button
              aria-label="更新未更新作者"
              icon={<SyncOutlined />}
              onClick={onBulkUpdate}
            >
              更新未更新作者
            </Button>
          ) : null
        }
      />
      <ProTable<Author>
        className="author-list-table"
        rowKey="id"
        headerTitle={view === 'list' ? batchActions : false}
        columns={columns}
        dataSource={data}
        search={false}
        tableViewRender={createAuthorTableViewRender(
          view,
          (author) => onSelect(author.id),
          (author) => <AuthorListActions author={author} onDetail={() => onSelect(author.id)} />,
          rowSelection,
          batchActions,
          { sort: cardSort, onSortChange: setCardSort },
        )}
        onChange={(_, __, sorter, extra) => {
          if (extra.action !== 'sort' || Array.isArray(sorter)) return;
          setTableSort(
            tableSortFromChange(
              sorter.columnKey ?? sorter.field,
              sorter.order,
              PROJECT_AUTHOR_TABLE_SORTS,
              'followers:desc',
            ),
          );
        }}
        scroll={{ x: 1190 }}
        pagination={{
          defaultPageSize: 20,
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 位`,
        }}
        options={view === 'list'
          ? { reload: false, density: true, setting: true, fullScreen: true }
          : false}
        columnsState={TABLE_COLUMN_PREFERENCES.projectAuthors}
        rowSelection={rowSelection}
        tableAlertRender={false}
        toolBarRender={view === 'list' ? () => [] : false}
      />
    </div>
  );
}
