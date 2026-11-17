<script setup lang="ts">
import { t as translate } from "../i18n";
</script>
<template>
  <section class="nf">
    <h1>{{ translate("页面不存在") }}</h1>
    <p class="muted">{{ translate("链接可能已失效。") }}</p>
    <RouterLink to="/" class="btn ghost">{{ translate("返回我的衣橱") }}</RouterLink>
  </section>
</template>

<style scoped>
.nf {
  max-width: 640px;
  margin: 80px auto;
  padding: 0 24px;
  display: grid;
  gap: 16px;
  justify-items: start;
}
h1 {
  font-size: 26px;
}
</style>
