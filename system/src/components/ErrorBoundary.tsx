import { Component, type ErrorInfo, type ReactNode } from "react";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("PLANT render error", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex h-full items-center justify-center bg-slate-50 p-6">
          <div className="max-w-xl rounded-card border border-red-200 bg-white p-5 shadow-sm">
            <p className="text-sm font-semibold text-red-700">畫面載入失敗</p>
            <p className="mt-2 text-xs leading-5 text-slate-600">
              {this.state.error.message || "請重新整理頁面後再試一次。"}
            </p>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
