import { describe, expect, it, vi } from 'vitest';
import { createPersistentRowSelection } from './persistentRowSelection';

describe('createPersistentRowSelection', () => {
  it('keeps selected row keys when the current page data changes', () => {
    const onSelectionChange = vi.fn();
    const rowSelection = createPersistentRowSelection<{ id: number }>(
      [1],
      onSelectionChange,
    );

    expect(rowSelection).toMatchObject({
      fixed: true,
      selectedRowKeys: [1],
      preserveSelectedRowKeys: true,
    });

    rowSelection.onChange?.(['1', 2], [], { type: 'multiple' });

    expect(onSelectionChange).toHaveBeenCalledWith([1, 2]);
  });
});
