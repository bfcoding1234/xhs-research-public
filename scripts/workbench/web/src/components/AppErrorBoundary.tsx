import { Button, Result } from 'antd';
import React from 'react';

interface State {
  error?: Error;
}

export default class AppErrorBoundary extends React.Component<React.PropsWithChildren, State> {
  override state: State = {};

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  override render() {
    if (this.state.error) {
      return (
        <Result
          status="500"
          title="页面出现问题"
          subTitle={this.state.error.message}
          extra={<Button onClick={() => window.location.reload()}>重新加载</Button>}
        />
      );
    }
    return this.props.children;
  }
}
