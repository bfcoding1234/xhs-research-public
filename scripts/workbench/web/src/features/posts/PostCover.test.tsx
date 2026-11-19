import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import PostCover from './PostCover';

describe('PostCover', () => {
  it('falls back from a failed local image to the remote cover', () => {
    render(<PostCover localSrc="/media/local.webp" remoteSrc="https://cdn.example/cover.webp" alt="帖子封面" />);

    fireEvent.error(screen.getByAltText('帖子封面'));

    expect(screen.getByAltText('帖子封面')).toHaveAttribute('src', 'https://cdn.example/cover.webp');
  });

  it('shows a placeholder after every source is exhausted', () => {
    render(<PostCover remoteSrc="https://cdn.example/expired.webp" alt="帖子封面" />);

    fireEvent.error(screen.getByAltText('帖子封面'));

    expect(screen.getByRole('img', { name: '帖子封面不可用' })).toHaveClass('cover-thumb');
  });

  it('can enable the large-image preview for list views', () => {
    render(
      <PostCover
        remoteSrc="https://cdn.example/cover.webp"
        alt="可预览封面"
        preview
      />,
    );

    fireEvent.click(screen.getByAltText('可预览封面').closest('.ant-image') as HTMLElement);

    expect(screen.getByRole('dialog', { name: '可预览封面' })).toBeInTheDocument();
  });
});
