import { useEffect, useState } from 'react';
import { Toast, ToastKind, dismissToast, subscribeToasts } from '../toast';

const STYLES: Record<ToastKind, string> = {
  error: 'bg-red-950/95 border-red-500/50 text-red-100',
  success: 'bg-green-950/95 border-green-500/50 text-green-100',
  info: 'bg-slate-800/95 border-slate-600 text-slate-100',
};

export function Toaster() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  useEffect(() => subscribeToasts(setToasts), []);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2 w-[22rem] max-w-[calc(100vw-2rem)]">
      {toasts.map((t) => (
        <div
          key={t.id}
          role="alert"
          className={`flex items-start gap-3 rounded-lg border px-4 py-3 shadow-2xl text-sm ${STYLES[t.kind]}`}
        >
          <span className="flex-1 break-words">{t.message}</span>
          <button
            onClick={() => dismissToast(t.id)}
            className="text-lg leading-none opacity-60 hover:opacity-100 transition-opacity"
            aria-label="Dismiss"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
