import { LinkOutlined, ReloadOutlined, SearchOutlined, UserOutlined } from '@ant-design/icons';
import type { ProColumns } from '@ant-design/pro-components';
import { PageContainer, ProTable } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { history, Link } from '@umijs/max';
import { Alert, Avatar, Button, Input, Space, Typography } from 'antd';
import { useMemo, useState } from 'react';
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
import AddToProjectModal from '@/features/references/AddToProjectModal';
import { createPersistentRowSelection } from '@/features/selection/persistentRowSelection';
import { apiService } from '@/services/api';
import { queryKeys } from '@/services/queryKeys';
import type { Author } from '@/types';
import {
  formatAuthorPostCoverage,
  sortAuthorsByFollowersDesc,
  storedAuthorPostCount,
} from '@/utils/authors';
import { formatDate, formatNumber } from '@/utils/format';

const GLOBAL_AUTHOR_TABLE_SORTS = [
  'name:asc',
  'name:desc',
  'followers:asc',
  'followers:desc',
  'posts:asc',
  'posts:desc',
  'projects:asc',
  'projects:desc',
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

export default function AuthorsPage() {
  const [query, setQuery] = useState('');
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [linkingIds, setLinkingIds] = useState<number[]>([]);
  const [view, setView] = useState<AuthorViewMode>(DEFAULT_AUTHOR_VIEW_MODE);
  const [tableSort, setTableSort] = useListSort(
    'authors.global.table',
    GLOBAL_AUTHOR_TABLE_SORTS,
    'followers:desc',
  );
  const [cardSort, setCardSort] = useListSort<AuthorCardSort>(
    'authors.global.card',
    AUTHOR_CARD_SORTS,
    'followers_desc',
  );
  const authors = useQuery({
    queryKey: queryKeys.authors,
    queryFn: ({ signal }) => apiService.authors(signal),
  });

  const data = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase('zh-CN');
    return sortAuthorsByFollowersDesc(
      (authors.data ?? []).filter(
        (author) =>
          !normalized ||
          [author.display_name, author.author_id, author.xhs_id, author.bio].some((value) =>
            String(value || '')
              .toLocaleLowerCase('zh-CN')
              .includes(normalized),
          ),
      ),
    );
  }, [authors.data, query]);

  const rowSelection = createPersistentRowSelection<Author>(selectedIds, setSelectedIds);

  const columns: ProColumns<Author>[] = [
    {
      title: '作者',
      dataIndex: 'display_name',
      width: 260,
      fixed: 'left',
      render: (_, row) => (
        <Space>
          <Avatar
            size={44}
            src={row.avatar_local_url || row.avatar_url || undefined}
            icon={<UserOutlined />}
          />
          <Space orientation="vertical" size={0}>
            <Link to={`/authors/${row.id}`}>{row.display_name || row.author_id}</Link>
            <Typography.Text type="secondary" className="mono">
              {row.author_id}
            </Typography.Text>
          </Space>
        </Space>
      ),
      sorter: (left, right) =>
        String(left.display_name).localeCompare(String(right.display_name), 'zh-CN'),
      key: 'name',
      sortOrder: tableSortOrder(tableSort, 'name'),
    },
    {
      title: '小红书号',
      dataIndex: 'xhs_id',
      width: 150,
      renderText: (value: string) => value || '—',
    },
    {
      title: 'IP 属地',
      dataIndex: 'ip_location',
      width: 120,
      renderText: (value: string) => value || '—',
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
      title: '帖子（已存/总数）',
      dataIndex: 'post_count',
      width: 160,
      align: 'right',
      render: (_, row) => formatAuthorPostCoverage(row),
      sorter: (left, right) => storedAuthorPostCount(left) - storedAuthorPostCount(right),
      key: 'posts',
      sortOrder: tableSortOrder(tableSort, 'posts'),
    },
    {
      title: '关联项目',
      dataIndex: 'project_count',
      width: 110,
      align: 'right',
      render: (_, row) => `${formatNumber(row.project_count ?? 0)} 个`,
      sorter: (left, right) => Number(left.project_count || 0) - Number(right.project_count || 0),
      key: 'projects',
      sortOrder: tableSortOrder(tableSort, 'projects'),
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
      render: (_, row) => (
        <AuthorListActions author={row} onDetail={() => history.push(`/authors/${row.id}`)} />
      ),
    },
  ];
  const batchActions = (
    <AuthorToolbarActions
      selectedCount={selectedIds.length}
      onClearSelection={() => setSelectedIds([])}
    >
      <AuthorBatchUpdateControl
        authors={authors.data ?? []}
        selectedIds={selectedIds}
        onSelectionChange={setSelectedIds}
      />
      <Button
        type="primary"
        icon={<LinkOutlined />}
        aria-label={selectedIds.length ? `关联到项目，已选 ${selectedIds.length} 位` : '关联到项目'}
        disabled={selectedIds.length === 0}
        onClick={() => setLinkingIds(selectedIds)}
      >
        关联到项目
      </Button>
    </AuthorToolbarActions>
  );

  return (
    <PageContainer
      title="作者"
      subTitle="全局作者主数据，以及每位作者名下的全部已采集帖子"
      extra={[
        <Button
          key="refresh"
          icon={<ReloadOutlined />}
          loading={authors.isFetching}
          onClick={() => authors.refetch()}
        >
          刷新
        </Button>,
      ]}
    >
      {authors.isError ? (
        <Alert
          showIcon
          type="error"
          title="作者列表加载失败"
          description={authors.error.message}
          action={<Button onClick={() => authors.refetch()}>重试</Button>}
        />
      ) : null}
      <AuthorListHeader
        title={`全部作者（${data.length}/${authors.data?.length ?? 0}）`}
        view={view}
        onViewChange={setView}
        query={(
          <Input
            allowClear
            prefix={<SearchOutlined />}
            value={query}
            aria-label="搜索作者名、作者 ID、小红书号或简介"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索作者"
          />
        )}
      />
      <ProTable<Author>
        className="author-list-table"
        rowKey="id"
        headerTitle={view === 'list' ? batchActions : false}
        loading={authors.isPending}
        columns={columns}
        dataSource={data}
        search={false}
        tableViewRender={createAuthorTableViewRender(
          view,
          (author) => history.push(`/authors/${author.id}`),
          (author) => (
            <AuthorListActions
              author={author}
              onDetail={() => history.push(`/authors/${author.id}`)}
            />
          ),
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
              GLOBAL_AUTHOR_TABLE_SORTS,
              'followers:desc',
            ),
          );
        }}
        scroll={{ x: 1290 }}
        pagination={{
          defaultPageSize: 20,
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 位`,
        }}
        options={view === 'list'
          ? { reload: false, density: true, setting: true, fullScreen: true }
          : false}
        columnsState={TABLE_COLUMN_PREFERENCES.globalAuthors}
        rowSelection={rowSelection}
        tableAlertRender={false}
        toolBarRender={view === 'list' ? () => [] : false}
      />
      <AddToProjectModal
        open={linkingIds.length > 0}
        entityType="author"
        entityIds={linkingIds}
        onClose={() => setLinkingIds([])}
        onSuccess={() => setSelectedIds([])}
      />
    </PageContainer>
  );
}
