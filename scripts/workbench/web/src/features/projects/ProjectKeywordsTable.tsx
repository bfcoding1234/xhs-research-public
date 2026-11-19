import {
  DeleteOutlined,
  PlusOutlined,
  RobotOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import type { ProColumns } from '@ant-design/pro-components';
import { ProTable } from '@ant-design/pro-components';
import { App, Button, Form, Input, Modal, Tag, Typography } from 'antd';
import { useEffect, useState } from 'react';
import { TABLE_COLUMN_PREFERENCES } from '@/features/preferences/tableColumnPreferences';
import type { Project, ProjectKeyword, ProjectKeywordSource } from '@/types';
import { createPersistentRowSelection } from '@/features/selection/persistentRowSelection';
import { formatDate } from '@/utils/format';
import KeywordSuggestionsModal from './KeywordSuggestionsModal';

interface ProjectKeywordsTableProps {
  project: Pick<Project, 'id' | 'name' | 'description'>;
  keywords: ProjectKeyword[];
  loading?: boolean;
  aiAvailable?: boolean;
  onAdd: (
    keywords: string[],
    source?: ProjectKeywordSource,
  ) => Promise<ProjectKeyword[]>;
  onRemove: (ids: number[]) => Promise<unknown>;
  onSearch: (keywords: string[]) => void;
}

function splitKeywords(value: string): string[] {
  return [...new Set(
    value.split(/[\n,，;；]/).map((item) => item.trim()).filter(Boolean),
  )];
}

export default function ProjectKeywordsTable({
  project,
  keywords,
  loading,
  aiAvailable = true,
  onAdd,
  onRemove,
  onSearch,
}: ProjectKeywordsTableProps) {
  const { message } = App.useApp();
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [adding, setAdding] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [value, setValue] = useState('');

  useEffect(() => {
    const available = new Set(keywords.map((keyword) => keyword.id));
    setSelectedIds((current) => current.filter((id) => available.has(id)));
  }, [keywords]);

  const selectedKeywords = keywords
    .filter((keyword) => selectedIds.includes(keyword.id))
    .map((keyword) => keyword.keyword);
  const columns: ProColumns<ProjectKeyword>[] = [
    {
      title: '关键词',
      dataIndex: 'keyword',
      width: 340,
      fixed: 'left',
      render: (_, row) => <Typography.Text>{row.keyword}</Typography.Text>,
    },
    {
      title: '来源',
      dataIndex: 'source',
      width: 140,
      render: (_, row) =>
        row.source === 'ai_generated'
          ? <Tag color="blue">AI 生成</Tag>
          : <Tag>手工添加</Tag>,
    },
    {
      title: '添加时间',
      dataIndex: 'created_at',
      width: 190,
      renderText: (date: string) => formatDate(date),
    },
  ];

  return (
    <>
      <ProTable<ProjectKeyword>
        rowKey="id"
        headerTitle={`项目关键词（${keywords.length}）`}
        loading={loading}
        columns={columns}
        dataSource={keywords}
        search={false}
        pagination={{ defaultPageSize: 20, showSizeChanger: true, showTotal: (total) => `共 ${total} 个` }}
        scroll={{ x: 700 }}
        options={{ reload: false, density: true, setting: true, fullScreen: true }}
        columnsState={TABLE_COLUMN_PREFERENCES.projectKeywords}
        rowSelection={createPersistentRowSelection<ProjectKeyword>(selectedIds, setSelectedIds)}
        tableAlertRender={false}
        toolBarRender={() => [
          <Button
            key="suggest"
            type="primary"
            icon={<RobotOutlined />}
            disabled={!aiAvailable}
            title={aiAvailable ? undefined : '当前服务未启用 Codex，暂时无法生成 AI 候选'}
            onClick={() => setSuggesting(true)}
          >
            AI 生成候选
          </Button>,
          <Button key="add" icon={<PlusOutlined />} onClick={() => setAdding(true)}>
            添加关键词
          </Button>,
          <Button
            key="search"
            icon={<SearchOutlined />}
            disabled={!selectedKeywords.length}
            onClick={() => onSearch(selectedKeywords)}
          >
            用所选关键词搜索
          </Button>,
          <Button
            key="remove"
            danger
            icon={<DeleteOutlined />}
            disabled={!selectedIds.length}
            onClick={() => void onRemove(selectedIds).then(() => setSelectedIds([])).catch(() => undefined)}
          >
            移除
          </Button>,
        ]}
      />
      <Modal
        title="添加关键词"
        open={adding}
        okText="添加"
        cancelText="取消"
        onCancel={() => {
          setAdding(false);
          setValue('');
        }}
        onOk={() => {
          const next = splitKeywords(value);
          if (!next.length) {
            message.warning('请至少输入一个关键词');
            return;
          }
          void onAdd(next, 'manual').then(() => {
            message.success('关键词已添加');
            setAdding(false);
            setValue('');
          }).catch(() => undefined);
        }}
        destroyOnHidden
      >
        <Form layout="vertical">
          <Form.Item label="关键词" extra="可用换行、逗号或分号分隔多个关键词。">
            <Input.TextArea
              value={value}
              onChange={(event) => setValue(event.target.value)}
              rows={5}
              maxLength={12000}
              placeholder={'例如：AI 产品经理\nAI 职业发展'}
            />
          </Form.Item>
        </Form>
      </Modal>
      <KeywordSuggestionsModal
        project={project}
        projectKeywords={keywords}
        open={suggesting}
        onClose={() => setSuggesting(false)}
        onAdd={(values, source) => onAdd(values, source)}
        onAdded={(added) =>
          setSelectedIds((current) => [
            ...new Set([...current, ...added.map((keyword) => keyword.id)]),
          ])
        }
      />
    </>
  );
}
