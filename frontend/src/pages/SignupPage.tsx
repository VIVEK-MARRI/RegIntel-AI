import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useAuth, authErrorMessage } from "@/providers/AuthProvider";
import { signup } from "@/services/api/authApi";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";

export function SignupPage() {
  const navigate = useNavigate();
  const { login, isAuthenticated, isLoading } = useAuth();
  // Hooks first, unconditionally — the early return below must never
  // change hook order (Rules-of-Hooks violation fixed).
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  if (!isLoading && isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (loading) return;
    const cleanEmail = email.trim().toLowerCase();
    const cleanName = fullName.trim();
    if (!cleanEmail) {
      setError("Email is required.");
      return;
    }
    if (password.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }
    setError("");
    setLoading(true);
    try {
      await signup({
        email: cleanEmail,
        password,
        full_name: cleanName || undefined,
      });
      // Establish the session through AuthProvider (single session logic).
      await login(cleanEmail, password);
      navigate("/", { replace: true });
    } catch (err: unknown) {
      setError(authErrorMessage(err, "signup"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-light-2 dark:bg-surface-dark">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-8 shadow-elevated dark:border-slate-700 dark:bg-surface-dark-2">
        <h1 className="mb-2 text-2xl font-bold text-slate-900 dark:text-slate-100">
          Create Account
        </h1>
        <p className="mb-6 text-sm text-slate-500 dark:text-slate-400">
          Register a new account to get started.
        </p>

        {error && (
          <div className="mb-4">
            <Alert tone="danger">{error}</Alert>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
              Full Name
            </label>
            <input
              type="text"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="Your name"
              className="input"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
              Email
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              required
              className="input"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 6 characters"
              required
              minLength={6}
              className="input"
            />
          </div>

          <Button
            type="submit"
            variant="primary"
            loading={loading}
            className="w-full"
          >
            {loading ? "Creating account..." : "Create Account"}
          </Button>
        </form>

        <p className="mt-6 text-center text-sm text-slate-500 dark:text-slate-400">
          Already have an account?{" "}
          <Link
            to="/login"
            className="font-medium text-brand-600 hover:text-brand-500 dark:text-brand-400"
          >
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}


