import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button, Result } from "antd";

interface Props {
  children: ReactNode;
  pageName: string;
}

interface State {
  hasError: boolean;
}

export default class PageErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Page failed to render", { error, componentStack: info.componentStack });
  }

  private reload = () => {
    window.location.reload();
  };

  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <Result
        status="error"
        title={`${this.props.pageName} 暂时无法加载`}
        subTitle="页面运行时发生错误，请重新加载后再试。"
        extra={<Button type="primary" onClick={this.reload}>重新加载</Button>}
      />
    );
  }
}
