import { Component, ErrorInfo, ReactNode } from "react";
import { AlertTriangle, RefreshCw, Home, ChevronDown, ChevronUp } from "lucide-react";
import { Button, Card, CardHeader, CardTitle, CardContent, CardFooter } from "./ui";

export interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
  onReset?: () => void;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
  showDetails: boolean;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
      showDetails: false,
    };
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return {
      hasError: true,
      error,
    };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    this.setState({ errorInfo });
    console.error("ErrorBoundary caught an unhandled rendering error:", error, errorInfo);
  }

  handleReset = (): void => {
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
      showDetails: false,
    });
    if (this.props.onReset) {
      this.props.onReset();
    }
  };

  handleReload = (): void => {
    window.location.reload();
  };

  handleGoHome = (): void => {
    window.location.href = "/";
  };

  toggleDetails = (): void => {
    this.setState((prev) => ({ showDetails: !prev.showDetails }));
  };

  render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      const errorMessage = this.state.error?.message || "An unexpected rendering error occurred.";
      const componentStack = this.state.errorInfo?.componentStack || "";

      return (
        <div className="min-h-screen bg-background flex items-center justify-center p-6 text-gray-100">
          <Card variant="default" className="max-w-2xl w-full border-red-900/60 shadow-2xl">
            <CardHeader className="border-b border-surfaceBorder/80">
              <CardTitle className="text-red-400 text-base">
                <AlertTriangle className="w-5 h-5 text-red-400" />
                Simulation Viewport Crashed
              </CardTitle>
            </CardHeader>

            <CardContent className="space-y-4">
              <p className="text-xs text-gray-300 leading-relaxed">
                The user interface caught an unhandled exception while rendering the current view.
                The backend orchestrator and sandbox workspaces remain safe and uncorrupted.
              </p>

              <div className="p-3 bg-red-950/40 border border-red-800/60 rounded-lg text-xs font-mono text-red-300 break-words">
                <strong>Error:</strong> {errorMessage}
              </div>

              <div>
                <button
                  type="button"
                  onClick={this.toggleDetails}
                  className="text-xs text-gray-400 hover:text-gray-200 flex items-center gap-1 transition select-none"
                >
                  {this.state.showDetails ? (
                    <>
                      <ChevronUp className="w-3.5 h-3.5" />
                      Hide Stack Trace
                    </>
                  ) : (
                    <>
                      <ChevronDown className="w-3.5 h-3.5" />
                      Show Diagnostic Stack Trace
                    </>
                  )}
                </button>

                {this.state.showDetails && (
                  <pre className="mt-2 p-3 bg-background/90 rounded-lg border border-surfaceBorder text-[11px] font-mono text-gray-400 overflow-x-auto max-h-48 leading-tight">
                    {this.state.error?.stack}
                    {componentStack}
                  </pre>
                )}
              </div>
            </CardContent>

            <CardFooter className="bg-surface/50 border-t border-surfaceBorder/80 flex items-center justify-between gap-3">
              <Button
                variant="ghost"
                size="sm"
                icon={<Home className="w-4 h-4" />}
                onClick={this.handleGoHome}
              >
                Command Center
              </Button>

              <div className="flex gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={this.handleReset}
                >
                  Try Recover View
                </Button>
                <Button
                  variant="primary"
                  size="sm"
                  icon={<RefreshCw className="w-4 h-4" />}
                  onClick={this.handleReload}
                >
                  Reload App
                </Button>
              </div>
            </CardFooter>
          </Card>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
