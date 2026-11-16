<script setup lang="ts">
import { dismiss, toasts } from "../lib/toast";

async function run(id: number, action: () => void | Promise<void>) {
  dismiss(id);
  await action();
}
</script>

<template>
  <div class="toasts" aria-live="polite">
    <div v-for="t in toasts" :key="t.id" class="toast" :class="t.kind" :role="t.kind === 'error' ? 'alert' : 'status'">
      <span class="text">{{ t.text }}</span>
      <button v-if="t.action" type="button" class="act" @click="run(t.id, t.action.run)">{{ t.action.label }}</button>
      <button type="button" class="close" aria-label="关闭提示" @click="dismiss(t.id)">×</button>
    </div>
  </div>
</template>

<style scoped>
.toasts {
  position: fixed;
  left: 50%;
  bottom: 20px;
  transform: translateX(-50%);
  z-index: 80;
  display: grid;
  gap: 8px;
  width: min(560px, calc(100vw - 32px));
}
.toast {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  background: var(--ink);
  color: #fff;
  border-radius: var(--radius);
  font-size: 14px;
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.18);
}
.toast.error {
  background: var(--danger);
}
.text {
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
}
.act {
  border: 1px solid rgba(255, 255, 255, 0.6);
  background: none;
  color: #fff;
  padding: 3px 10px;
  border-radius: var(--radius);
  cursor: pointer;
  font-weight: 600;
}
.close {
  border: 0;
  background: none;
  color: #fff;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  padding: 0 2px;
}
</style>
