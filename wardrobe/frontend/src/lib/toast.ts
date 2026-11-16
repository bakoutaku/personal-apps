// 轻量的全局提示（操作结果 / 可撤销的删除）。由 App.vue 中的 ToastHost 显示。
import { reactive } from "vue";

export interface Toast {
  id: number;
  text: string;
  kind: "info" | "error";
  action?: { label: string; run: () => void | Promise<void> };
}

export const toasts = reactive<Toast[]>([]);
let nextId = 1;

export function notify(text: string, opts: { kind?: Toast["kind"]; action?: Toast["action"]; timeout?: number } = {}): number {
  const id = nextId++;
  toasts.push({ id, text, kind: opts.kind ?? "info", action: opts.action });
  // 带「撤销」等操作的提示停留更久，给用户反应时间
  const timeout = opts.timeout ?? (opts.action ? 10000 : 4000);
  if (timeout > 0) setTimeout(() => dismiss(id), timeout);
  return id;
}

export function dismiss(id: number) {
  const i = toasts.findIndex((t) => t.id === id);
  if (i >= 0) toasts.splice(i, 1);
}
