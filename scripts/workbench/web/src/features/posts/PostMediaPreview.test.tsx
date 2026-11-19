import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { MediaAsset } from '@/types';
import PostMediaPreview, { mediaSourceLabel } from './PostMediaPreview';

const media: MediaAsset = {
  id: 1,
  post_id: 2,
  media_index: 1,
  media_type: 'image',
  original_url: 'https://cdn.example/original.webp',
  local_path: '/tmp/local.webp',
  local_url: '/media/local.webp',
  ocr_text: '',
  ocr_engine: '',
  download_status: 'downloaded',
  updated_at: '2026-07-17T00:00:00Z',
};

describe('PostMediaPreview', () => {
  it('uses the recorded original URL when no local media was saved', () => {
    render(<PostMediaPreview media={{ ...media, local_path: '', local_url: '', download_status: 'remote' }} alt="正文媒体" />);

    expect(screen.getByAltText('正文媒体')).toHaveAttribute('src', media.original_url);
    expect(mediaSourceLabel({ ...media, local_path: '', local_url: '', download_status: 'remote' })).toBe('远程图片');
    expect(screen.getByAltText('正文媒体')).toHaveAttribute('referrerpolicy', 'no-referrer');
  });

  it('falls back to the original URL if a local copy becomes unavailable', () => {
    render(<PostMediaPreview media={media} alt="正文媒体" />);

    fireEvent.error(screen.getByAltText('正文媒体'));

    expect(screen.getByAltText('正文媒体')).toHaveAttribute('src', media.original_url);
    expect(screen.getByAltText('正文媒体')).toHaveAttribute('referrerpolicy', 'no-referrer');
  });
});
