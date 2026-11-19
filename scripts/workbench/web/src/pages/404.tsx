import { Button, Result } from 'antd';
import { history } from '@umijs/max';

export default function NotFoundPage() {
  return (
    <Result
      status="404"
      title="页面不存在"
      subTitle="这个地址没有对应的工作台页面。"
      extra={<Button type="primary" onClick={() => history.push('/projects')}>返回项目</Button>}
    />
  );
}
