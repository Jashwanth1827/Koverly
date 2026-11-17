import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

type ToastTone = "success" | "error" | "info";

interface ToastItem {
  id: number;
  tone: ToastTone;
  message: string;
}

interface ToastApi {
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);
let nextId = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const push = useCallback((tone: ToastTone, message: string) => {
    if (!message) return;
    const id = ++nextId;
    setItems((current) => [...current.slice(-2), { id, tone, message }]);
    window.setTimeout(() => {
      setItems((current) => current.filter((item) => item.id !== id));
    }, 5000);
  }, []);

  const api: ToastApi = {
    success: (message) => push("success", message),
    error: (message) => push("error", message),
    info: (message) => push("info", message),
  };

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        className="pointer-events-none fixed bottom-20 right-3 z-[60] flex w-[min(22rem,calc(100vw-1.5rem))] flex-col gap-2 sm:bottom-4 sm:right-4"
        aria-live="polite"
        aria-atomic="false"
      >
        {items.map((item) => (
          <div
            key={item.id}
            role={item.tone === "error" ? "alert" : "status"}
            className={`pointer-events-auto flex items-start gap-2 rounded-lg border px-3 py-2 text-sm shadow-lg ${
              item.tone === "success"
                ? "border-emerald-200 bg-emerald-50 text-emerald-900"
                : item.tone === "error"
                  ? "border-red-200 bg-red-50 text-red-900"
                  : "border-slate-200 bg-white text-ink-900"
            }`}
          >
            <span aria-hidden className="font-semibold">
              {item.tone === "success" ? "✓" : item.tone === "error" ? "!" : "i"}
            </span>
            <span className="min-w-0 flex-1 break-words">{item.message}</span>
            <button
              type="button"
              className="-mr-1 -mt-0.5 px-1 text-base leading-none opacity-60 hover:opacity-100"
              aria-label="Dismiss notification"
              onClick={() => setItems((current) => current.filter((i) => i.id !== item.id))}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}
