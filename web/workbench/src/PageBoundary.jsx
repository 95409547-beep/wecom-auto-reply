import { Component } from 'react';

export class PageBoundary extends Component {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error, info) {
    console.error('Workbench page failed', error, info.componentStack);
  }

  render() {
    if (this.state.failed) {
      return <section className="page-error" role="alert">
        <h2>{this.props.title || '工作区'}暂时无法显示</h2>
        <button className="button secondary" onClick={() => this.setState({ failed: false })}>重新加载</button>
      </section>;
    }
    return this.props.children;
  }
}
