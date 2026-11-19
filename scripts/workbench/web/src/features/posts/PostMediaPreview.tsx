import { FileImageOutlined } from '@ant-design/icons';
import { Image } from 'antd';
import { useEffect, useState } from 'react';
import type { MediaAsset } from '@/types';

export function mediaSourceLabel(media: MediaAsset): string {
  if (media.local_url) return '本地图片';
  if (media.original_url) return '远程图片';
  return media.download_status || '媒体不可用';
}

export function mediaSourceColor(media: MediaAsset): 'success' | 'processing' | 'default' {
  if (media.local_url) return 'success';
  return media.original_url ? 'processing' : 'default';
}

export default function PostMediaPreview({
  media,
  alt,
  preview = true,
}: {
  media: MediaAsset;
  alt: string;
  preview?: boolean;
}) {
  const localSrc = media.local_url;
  const remoteSrc = media.original_url;
  const [src, setSrc] = useState(localSrc || remoteSrc || '');

  useEffect(() => {
    setSrc(localSrc || remoteSrc || '');
  }, [localSrc, remoteSrc]);

  if (!src) return <FileImageOutlined className="post-detail-media-placeholder" />;

  return (
    <Image
      src={src}
      alt={alt}
      preview={preview}
      referrerPolicy={src === remoteSrc ? 'no-referrer' : undefined}
      style={{ objectFit: 'contain' }}
      onError={() => {
        if (src === localSrc && remoteSrc && remoteSrc !== localSrc) {
          setSrc(remoteSrc);
        } else {
          setSrc('');
        }
      }}
    />
  );
}
