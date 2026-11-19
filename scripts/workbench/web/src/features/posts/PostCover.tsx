import { Image } from 'antd';
import type { CSSProperties } from 'react';
import { useEffect, useState } from 'react';

export default function PostCover({
  localSrc,
  remoteSrc,
  alt,
  className,
  width = 48,
  height = 64,
  preview = false,
}: {
  localSrc?: string;
  remoteSrc?: string;
  alt: string;
  className?: string;
  width?: string | number;
  height?: string | number;
  preview?: boolean;
}) {
  const [src, setSrc] = useState(localSrc || remoteSrc || '');

  useEffect(() => {
    setSrc(localSrc || remoteSrc || '');
  }, [localSrc, remoteSrc]);

  if (!src) {
    return (
      <div
        className={className ? `${className} cover-thumb` : 'cover-thumb'}
        role="img"
        aria-label={`${alt}不可用`}
        style={{ width, height } as CSSProperties}
      />
    );
  }

  return (
    <Image
      className={className}
      width={width}
      height={height}
      src={src}
      alt={alt}
      preview={preview}
      style={{ objectFit: 'cover', borderRadius: 4 }}
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
