import { onScopeDispose, readonly, ref, watch, type Ref } from "vue";

// 请求立即开始/结束；只延后可见反馈，避免快速请求闪过加载提示。
export function useDelayedLoading(loading: Ref<boolean>) {
  const visible = ref(false);
  let timer: ReturnType<typeof setTimeout> | undefined;
  const clear = () => { clearTimeout(timer); timer = undefined; };
  watch(loading, (pending) => {
    clear();
    visible.value = false;
    if (pending) timer = setTimeout(() => { visible.value = true; }, 150);
  }, { immediate: true, flush: "sync" });
  onScopeDispose(clear);
  return readonly(visible);
}
