import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import PostOriginalLink from './PostOriginalLink';

describe('PostOriginalLink', () => {
  it('opens the original post in a new tab', () => {
    render(<PostOriginalLink noteUrl="https://www.xiaohongshu.com/explore/note-1" />);

    expect(screen.getByRole('link', { name: /原文/ })).toHaveAttribute(
      'href',
      'https://www.xiaohongshu.com/explore/note-1',
    );
    expect(screen.getByRole('link', { name: /原文/ })).toHaveAttribute('target', '_blank');
    expect(screen.getByRole('link', { name: /原文/ })).toHaveAttribute(
      'rel',
      'noopener noreferrer',
    );
  });

  it('is disabled when the original link is unavailable', () => {
    render(<PostOriginalLink />);

    expect(screen.getByRole('button', { name: /原文/ })).toBeDisabled();
  });
});
