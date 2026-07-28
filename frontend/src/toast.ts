// Minimal pub/sub toast store, usable from anywhere (components or the API
// client) without prop drilling or a context provider. Components subscribe;
// call sites push.

export type ToastKind = 'error' | 'success' | 'info';

export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

type Listener = (toasts: Toast[]) => void;

let toasts: Toast[] = [];
const listeners = new Set<Listener>();
let nextId = 1;

function emit() {
  const snapshot = [...toasts];
  for (const listener of listeners) listener(snapshot);
}

export function subscribeToasts(listener: Listener): () => void {
  listeners.add(listener);
  listener([...toasts]);
  return () => {
    listeners.delete(listener);
  };
}

export function dismissToast(id: number) {
  toasts = toasts.filter((t) => t.id !== id);
  emit();
}

export function pushToast(message: string, kind: ToastKind = 'error', timeoutMs = 6000): number {
  const id = nextId++;
  toasts = [...toasts, { id, kind, message }];
  emit();
  if (timeoutMs > 0) {
    setTimeout(() => dismissToast(id), timeoutMs);
  }
  return id;
}
