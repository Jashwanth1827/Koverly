import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { ApiError } from "@/api/client";
import { AppFooter } from "@/components/Footer";
import { useToast } from "@/components/Toast";
import { usePageMeta } from "@/lib/pageMeta";

export function LoginPage() {
  const { login, register, user } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [revealPassword, setRevealPassword] = useState(false);
  const [hoverPassword, setHoverPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const showPassword = revealPassword || hoverPassword;
  usePageMeta(mode === "login" ? "Sign in" : "Create account");

  if (user) return <Navigate to="/" replace />;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "login") await login(email, password);
      else await register(email, name, password);
      toast.success(mode === "login" ? "Signed in successfully." : "Your account is ready.");
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to sign in.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-full flex-col items-center justify-center px-4 py-12">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-brand-600 text-lg font-bold text-white">
            K
          </span>
          <h1 className="mt-4 text-2xl font-semibold tracking-tight">Koverly</h1>
          <p className="mt-1 text-sm text-ink-500">
            Understand, manage, and use every insurance policy your family owns.
          </p>
        </div>

        <div className="card p-6">
          <div className="mb-5 flex rounded-lg bg-slate-100 p-1 text-sm font-medium">
            {(["login", "register"] as const).map((m) => (
              <button
                key={m}
                className={`flex-1 rounded-md py-1.5 ${
                  mode === m ? "bg-white shadow-sm text-ink-900" : "text-ink-500"
                }`}
                onClick={() => setMode(m)}
                type="button"
              >
                {m === "login" ? "Sign in" : "Create account"}
              </button>
            ))}
          </div>

          <form onSubmit={submit} className="space-y-4">
            {mode === "register" && (
              <div>
                <label className="label" htmlFor="name">
                  Full name
                </label>
                <input
                  id="name"
                  className="input"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                  autoComplete="name"
                />
              </div>
            )}
            <div>
              <label className="label" htmlFor="email">
                Email
              </label>
              <input
                id="email"
                type="email"
                className="input"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="email"
              />
            </div>
            <div>
              <label className="label" htmlFor="password">
                Password
              </label>
              <div className="relative">
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  className="input pr-20"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  minLength={mode === "register" ? 7 : undefined}
                />
                <button
                  type="button"
                  className="absolute inset-y-0 right-0 flex items-center px-3 text-xs font-medium text-brand-600 hover:text-brand-700 focus:outline-none"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  onMouseEnter={() => setHoverPassword(true)}
                  onMouseLeave={() => setHoverPassword(false)}
                  onFocus={() => setHoverPassword(true)}
                  onBlur={() => setHoverPassword(false)}
                  onClick={() => setRevealPassword((visible) => !visible)}
                >
                  {showPassword ? "Hide" : "Show"}
                </button>
              </div>
              {mode === "register" && (
                <p className="mt-1 text-xs text-ink-500">
                  At least 7 characters, with a mix of letters, numbers, or symbols.
                </p>
              )}
            </div>

            {error && (
              <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </p>
            )}

            <button className="btn-primary w-full" disabled={busy}>
              {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
            </button>
          </form>
        </div>

        <p className="mt-6 text-center text-xs text-ink-300">
          Koverly is an organizational and informational tool. It is not an insurer, lawyer, doctor,
          or financial adviser.
        </p>
        <AppFooter />
      </div>
    </div>
  );
}
