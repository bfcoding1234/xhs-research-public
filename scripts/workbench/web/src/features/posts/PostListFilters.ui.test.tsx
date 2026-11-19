import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import PostListFilters, {
  DEFAULT_POST_LIST_FILTERS,
  type PostListFilterState,
} from './PostListFilters';

describe('PostListFilters', () => {
  it('keeps OCR status visible and stages low-frequency filters in more filters', () => {
    const changes = vi.fn();

    function Harness() {
      const [filters, setFilters] = useState<PostListFilterState>(DEFAULT_POST_LIST_FILTERS);
      return (
        <>
          <output data-testid="ocr-filter">{filters.ocr}</output>
          <PostListFilters
            value={filters}
            onChange={(next) => {
              changes(next);
              setFilters(next);
            }}
          />
        </>
      );
    }

    render(<Harness />);

    expect(screen.getByRole('searchbox', { name: '搜索标题、正文、作者、来源或帖子 ID' }))
      .toBeInTheDocument();
    const ocrSelect = screen.getByRole('combobox', { name: '按 OCR 识图状态筛选' });
    fireEvent.mouseDown(ocrSelect);
    const pendingOptions = screen.getAllByText('待执行 OCR');
    fireEvent.click(pendingOptions[pendingOptions.length - 1] as HTMLElement);

    expect(screen.getByTestId('ocr-filter')).toHaveTextContent('pending');
    expect(changes).toHaveBeenLastCalledWith({
      ...DEFAULT_POST_LIST_FILTERS,
      ocr: 'pending',
    });

    fireEvent.click(screen.getByRole('button', { name: /更多筛选/ }));
    fireEvent.click(screen.getByRole('button', { name: '重置' }));

    expect(screen.getByTestId('ocr-filter')).toHaveTextContent('pending');
  });

  it('stages an entry-specific media storage filter until confirmation', () => {
    const changes = vi.fn();

    function Harness() {
      const [mediaStorage, setMediaStorage] = useState('all');
      return (
        <>
          <output data-testid="media-storage-filter">{mediaStorage}</output>
          <PostListFilters
            value={DEFAULT_POST_LIST_FILTERS}
            onChange={() => undefined}
            additionalFilters={[
              {
                key: 'media_storage',
                label: '媒体存储状态',
                ariaLabel: '按媒体存储状态筛选',
                value: mediaStorage,
                options: [
                  { value: 'all', label: '全部媒体状态' },
                  { value: 'remote', label: '远程图片待下载' },
                ],
                onChange: (next) => {
                  changes(next);
                  setMediaStorage(next);
                },
              },
            ]}
          />
        </>
      );
    }

    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: /更多筛选/ }));
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '按媒体存储状态筛选' }));
    fireEvent.click(screen.getByText('远程图片待下载'));
    expect(screen.getByTestId('media-storage-filter')).toHaveTextContent('all');

    fireEvent.click(screen.getByRole('button', { name: '确定' }));
    expect(changes).toHaveBeenCalledWith('remote');
    expect(screen.getByTestId('media-storage-filter')).toHaveTextContent('remote');
  });
});
