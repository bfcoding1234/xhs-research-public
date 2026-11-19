import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Author } from '@/types';
import AuthorListActions from './AuthorListActions';

const author = {
  id: 1,
  author_id: 'author-a',
  display_name: '作者 A',
  profile_url: 'https://www.xiaohongshu.com/user/profile/author-a',
} as Author;

describe('AuthorListActions', () => {
  it('only shows homepage and detail actions', () => {
    const onDetail = vi.fn();
    render(<AuthorListActions author={author} onDetail={onDetail} />);

    const profile = screen.getByRole('link', { name: '主页' });
    expect(profile).toHaveAttribute('href', author.profile_url);
    expect(profile).toHaveAttribute('target', '_blank');
    expect(screen.queryByText('更新基础信息')).not.toBeInTheDocument();
    expect(screen.queryByText('关联')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '详情' }));
    expect(onDetail).toHaveBeenCalledOnce();
  });
});
