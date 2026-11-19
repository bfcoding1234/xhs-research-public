import { ExportOutlined } from '@ant-design/icons';
import { Button } from 'antd';

export default function PostOriginalLink({ noteUrl }: { noteUrl?: string }) {
  return (
    <Button
      type="link"
      icon={<ExportOutlined />}
      href={noteUrl || undefined}
      target={noteUrl ? '_blank' : undefined}
      rel={noteUrl ? 'noopener noreferrer' : undefined}
      disabled={!noteUrl}
      title={noteUrl ? '在新标签页打开原文' : '暂无原文链接'}
    >
      原文
    </Button>
  );
}
