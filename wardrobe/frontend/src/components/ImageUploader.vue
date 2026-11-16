<script setup lang="ts">
import { ref } from "vue";
import { api } from "../api/client";
import type { ImageInfo } from "../api/types";
import { errorMessage } from "../lib/errors";

// onUploaded 用 prop 声明（模板里仍写 @uploaded）而不是 emit：emit 不会等待父组件的异步处理，
// 多张图片的关联请求会同时带着同一个旧 version 发出。返回 false 表示关联失败，停止处理后续文件。
const props = withDefaults(
  defineProps<{
    label?: string;
    sourceType?: string;
    disabled?: boolean;
    onUploaded?: (image: ImageInfo) => boolean | void | Promise<boolean | void>;
  }>(),
  { label: "上传图片", sourceType: "user_photo", disabled: false, onUploaded: undefined },
);
const busy = ref(false);
const error = ref<string | null>(null);
const input = ref<HTMLInputElement | null>(null);

async function onChange(event: Event) {
  const files = [...((event.target as HTMLInputElement).files ?? [])];
  error.value = null;
  busy.value = true;
  try {
    // 逐个上传并等待父组件关联完成；任何一张失败都停下（已完成的保留，失败原因由父组件显示）
    for (const file of files) {
      const image = await api.uploadImage(file, props.sourceType);
      if ((await props.onUploaded?.(image)) === false) break;
    }
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
    if (input.value) input.value.value = "";
  }
}
</script>

<template>
  <div class="uploader">
    <label class="btn ghost small" :class="{ disabled: disabled || busy }">
      {{ busy ? "上传中…" : label }}
      <input
        ref="input"
        type="file"
        accept="image/jpeg,image/png,image/webp,image/heic"
        multiple
        class="visually-hidden"
        :disabled="disabled || busy"
        @change="onChange"
      />
    </label>
    <p v-if="error" class="field-error" role="alert">{{ error }}</p>
  </div>
</template>

<style scoped>
.uploader {
  display: grid;
  gap: 6px;
  justify-items: start;
}
label.btn:focus-within {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}
.disabled {
  opacity: 0.45;
  pointer-events: none;
}
</style>
