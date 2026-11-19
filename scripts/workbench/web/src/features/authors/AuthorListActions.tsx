import { ExportOutlined, EyeOutlined } from '@ant-design/icons';
import { Button } from 'antd';
import type { Author } from '@/types';
import { authorProfileUrl } from '@/utils/authors';

export default function AuthorListActions({
  author,
  onDetail,
}: {
  author: Author;
  onDetail: () => void;
}) {
  return (
    <>
      <Button
        type="link"
        aria-label="主页"
        icon={<ExportOutlined />}
        href={authorProfileUrl(author)}
        target="_blank"
        rel="noreferrer"
      >
        主页
      </Button>
      <Button type="link" aria-label="详情" icon={<EyeOutlined />} onClick={onDetail}>
        详情
      </Button>
    </>
  );
}
