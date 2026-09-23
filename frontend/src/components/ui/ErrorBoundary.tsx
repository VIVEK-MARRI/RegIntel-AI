import { Component, type ReactNode } from "react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";

interface ErrorBoundaryProps {
  /** When this value changes the boundary resets (e.g. route pathname). */
  resetKey?: string;
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * Last-resort render guard: a page crash shows a localized fallback with
 * navigation intact instead of blanking the application. Per-region
 * ErrorState handling remains the primary strategy; this catches only
 * unexpected render failures. Never renders error stacks or secrets.
 */
export class AppErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidUpdate(prevProps: ErrorBoundaryProps) {
    if (prevProps.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="mx-auto w-full max-w-2xl px-4 py-10" role="alert">
        <Card padding="md">
          <h2 className="text-base font-bold text-slate-900 dark:text-white">
            Something went wrong on this page
          </h2>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            The rest of the application is unaffected. Reloading usually
            resolves transient render failures; if it persists, the page data
            may be malformed.
          </p>
          <div className="mt-4 flex gap-2">
            <Button
              variant="primary"
              size="sm"
              onClick={() => window.location.reload()}
            >
              Reload application
            </Button>
          </div>
        </Card>
      </div>
    );
  }
}
