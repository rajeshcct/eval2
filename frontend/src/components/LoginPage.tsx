import { useState, useEffect } from "react";
import { login, register, checkSetupStatus } from "../lib/auth";
import type { AuthUser } from "../lib/auth";

interface LoginPageProps {
  onAuth: (user: AuthUser) => void;
}

export default function LoginPage({ onAuth }: LoginPageProps) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [needsSetup, setNeedsSetup] = useState<boolean | null>(null);
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    checkSetupStatus()
      .then(({ needs_setup }) => {
        setNeedsSetup(needs_setup);
        if (needs_setup) setMode("register");
      })
      .catch(() => setNeedsSetup(false));
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (mode === "register") {
      if (password !== confirmPassword) {
        setError("Passwords do not match.");
        return;
      }
      if (password.length < 6) {
        setError("Password must be at least 6 characters.");
        return;
      }
    }

    setLoading(true);
    try {
      let user: AuthUser;
      if (mode === "register") {
        user = await register(username.trim(), password, displayName.trim() || username.trim());
      } else {
        user = await login(username.trim(), password);
      }
      onAuth(user);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  if (needsSetup === null) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-slate-700 border-t-indigo-400" />
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      {/* Background glow elements */}
      <div className="pointer-events-none fixed inset-0 overflow-hidden">
        <div className="absolute -top-32 left-1/4 h-[500px] w-[500px] rounded-full bg-indigo-600/10 blur-[120px]" />
        <div className="absolute bottom-0 right-1/4 h-[400px] w-[400px] rounded-full bg-violet-600/10 blur-[100px]" />
      </div>

      <div className="relative w-full max-w-md">
        {/* Logo / Brand */}
        <div className="mb-8 text-center">
          <div className="mb-3 inline-flex h-14 w-14 items-center justify-center rounded-2xl border border-indigo-500/30 bg-indigo-600/10 shadow-lg shadow-indigo-500/10">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" className="text-indigo-400">
              <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-50">EvalMind</h1>
          <p className="mt-1 text-sm text-slate-400">AI Evaluation Workspace</p>
        </div>

        {/* Card */}
        <div className="rounded-2xl border border-slate-700/60 bg-slate-900/80 p-8 shadow-2xl shadow-black/40 backdrop-blur-sm">
          {needsSetup && (
            <div className="mb-6 rounded-lg border border-amber-700/40 bg-amber-950/30 px-4 py-3">
              <p className="text-sm font-medium text-amber-300">👋 First time setup</p>
              <p className="mt-1 text-xs text-amber-400/80">
                No users exist yet. Create an admin account to get started.
              </p>
            </div>
          )}

          <h2 className="mb-6 text-lg font-semibold text-slate-100">
            {mode === "register" ? (needsSetup ? "Create Admin Account" : "Create Account") : "Sign In"}
          </h2>

          <form onSubmit={(e) => void handleSubmit(e)} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="login_username" className="text-xs font-medium uppercase tracking-wider text-slate-400">
                Username
              </label>
              <input
                id="login_username"
                type="text"
                autoComplete="username"
                autoFocus
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500/50 transition-colors"
                placeholder="your_username"
              />
            </div>

            {mode === "register" && (
              <div className="flex flex-col gap-1.5">
                <label htmlFor="login_display_name" className="text-xs font-medium uppercase tracking-wider text-slate-400">
                  Display name <span className="text-slate-600 normal-case">(optional)</span>
                </label>
                <input
                  id="login_display_name"
                  type="text"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  className="rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500/50 transition-colors"
                  placeholder="Your Name"
                />
              </div>
            )}

            <div className="flex flex-col gap-1.5">
              <label htmlFor="login_password" className="text-xs font-medium uppercase tracking-wider text-slate-400">
                Password
              </label>
              <input
                id="login_password"
                type="password"
                autoComplete={mode === "register" ? "new-password" : "current-password"}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500/50 transition-colors"
                placeholder="••••••••"
              />
            </div>

            {mode === "register" && (
              <div className="flex flex-col gap-1.5">
                <label htmlFor="login_confirm" className="text-xs font-medium uppercase tracking-wider text-slate-400">
                  Confirm Password
                </label>
                <input
                  id="login_confirm"
                  type="password"
                  autoComplete="new-password"
                  required
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className="rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500/50 transition-colors"
                  placeholder="••••••••"
                />
              </div>
            )}

            {error && (
              <div role="alert" className="rounded-lg border border-red-800/60 bg-red-950/40 px-3 py-2.5 text-sm text-red-300">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="mt-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-indigo-500/20 transition-all hover:bg-indigo-500 hover:shadow-indigo-500/30 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400 disabled:shadow-none"
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                  {mode === "register" ? "Creating account…" : "Signing in…"}
                </span>
              ) : mode === "register" ? "Create Account" : "Sign In"}
            </button>
          </form>

          {!needsSetup && (
            <p className="mt-5 text-center text-xs text-slate-500">
              {mode === "login" ? (
                <>
                  Don't have an account?{" "}
                  <button
                    type="button"
                    onClick={() => { setMode("register"); setError(null); }}
                    className="text-indigo-400 hover:text-indigo-300 transition-colors"
                  >
                    Create one
                  </button>
                </>
              ) : (
                <>
                  Already have an account?{" "}
                  <button
                    type="button"
                    onClick={() => { setMode("login"); setError(null); }}
                    className="text-indigo-400 hover:text-indigo-300 transition-colors"
                  >
                    Sign in
                  </button>
                </>
              )}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
