import { useState, type FormEvent } from "react";
import { useNavigate, useLocation, Link, Navigate } from "react-router-dom";
import { useAuth } from "@/providers/AuthProvider";

export function LoginPage() {
  const { login, isAuthenticated, isLoading } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const from = (location.state as { from?: string })?.from || "/";

  // Already authenticated → redirect
  if (!isLoading && isAuthenticated) {
    return <Navigate to={from} replace />;
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await login(email, password);
      navigate(from, { replace: true });
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : "Login failed. Please try again.";
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-light-2 p-4 dark:bg-surface-dark">
      <div className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-8 shadow-elevated dark:border-slate-700 dark:bg-surface-dark-2">
        <div className="mb-6 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-2xl text-white shadow-glow">
            ⌬
          </div>
          <h1 className="text-xl font-bold text-slate-900 dark:text-slate-100">
            RegIntel AI
          </h1>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Sign in to continue
          </p>
          <details className="mt-2 text-left text-[10px] text-slate-400 dark:text-slate-500">
            <summary className="cursor-pointer hover:text-slate-600 dark:hover:text-slate-300">
              Demo credentials
            </summary>
            <div className="mt-1 space-y-0.5">
              <div>admin@regintel.ai / Admin@123</div>
              <div>analyst@regintel.ai / Analyst@123</div>
              <div>auditor@regintel.ai / Auditor@123</div>
            </div>
          </details>
        </div>

        {error ? (
          <div
            className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900/40 dark:bg-red-950/30 dark:text-red-300"
            role="alert"
          >
            {error}
          </div>
        ) : null}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label
              htmlFor="email"
              className="mb-1 block text-xs font-medium text-slate-700 dark:text-slate-300"
            >
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              autoFocus
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder-slate-400 transition focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20 dark:border-slate-600 dark:bg-surface-dark-3 dark:text-slate-100 dark:placeholder-slate-500"
              placeholder="you@company.com"
            />
          </div>

          <div>
            <label
              htmlFor="password"
              className="mb-1 block text-xs font-medium text-slate-700 dark:text-slate-300"
            >
              Password
            </label>
            <input
              id="password"
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder-slate-400 transition focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20 dark:border-slate-600 dark:bg-surface-dark-3 dark:text-slate-100 dark:placeholder-slate-500"
              placeholder="••••••••"
            />
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <p className="mt-6 text-center text-xs text-slate-500 dark:text-slate-400">
          Don't have an account?{" "}
          <Link
            to="/signup"
            className="font-medium text-brand-600 hover:text-brand-500 dark:text-brand-400"
          >
            Create one
          </Link>
        </p>
      </div>
    </div>
  );
}
