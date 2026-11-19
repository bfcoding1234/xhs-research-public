import type { TableProps } from 'antd';

export function createPersistentRowSelection<T>(
  selectedIds: number[],
  onSelectionChange: (ids: number[]) => void,
): NonNullable<TableProps<T>['rowSelection']> {
  return {
    fixed: true,
    selectedRowKeys: selectedIds,
    preserveSelectedRowKeys: true,
    onChange: (keys) => onSelectionChange(keys.map(Number)),
  };
}
