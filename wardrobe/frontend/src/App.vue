<script setup lang="ts">
import { RouterLink, RouterView } from "vue-router";
import ToastHost from "./components/ToastHost.vue";

const nav = [
  { to: "/", label: "我的衣橱", section: "wardrobe" },
  { to: "/overview", label: "衣橱总览", section: "overview" },
  { to: "/outfits", label: "穿搭组合", section: "outfits" },
  { to: "/purchases", label: "购买记录", section: "purchases" },
  { to: "/imports", label: "导入中心", section: "imports" },
  { to: "/settings", label: "设置", section: "settings" },
];
</script>

<template>
  <a class="skip-link" href="#main">跳到主要内容</a>
  <header class="site-header">
    <div class="inner">
      <RouterLink to="/" class="wordmark" aria-label="Wardrobe 首页">WARDROBE</RouterLink>
      <nav aria-label="主导航">
        <RouterLink
          v-for="n in nav"
          :key="n.to"
          :to="n.to"
          class="nav-link"
          :class="{ active: $route.meta.section === n.section }"
        >
          {{ n.label }}
        </RouterLink>
      </nav>
    </div>
  </header>
  <main id="main">
    <RouterView v-slot="{ Component }">
      <!-- 不用 out-in 或 fullPath key：导航不等待退场，同页参数更新继续复用实例。 -->
      <Transition name="page">
        <KeepAlive include="WardrobeView">
          <component :is="Component" />
        </KeepAlive>
      </Transition>
    </RouterView>
  </main>
  <ToastHost />
</template>

<style scoped>
.skip-link {
  position: absolute;
  left: -999px;
  top: 8px;
  background: var(--ink);
  color: #fff;
  padding: 8px 12px;
  z-index: 100;
}
.skip-link:focus {
  left: 8px;
}
.site-header {
  position: sticky;
  top: 0;
  z-index: 20;
  height: var(--header-h);
  background: rgba(255, 255, 255, 0.96);
  border-bottom: 1px solid var(--line);
  backdrop-filter: saturate(1.2) blur(6px);
}
.inner {
  max-width: 1600px;
  height: 100%;
  margin: 0 auto;
  padding: 0 24px;
  display: flex;
  align-items: center;
  gap: 40px;
}
.wordmark {
  font-weight: 800;
  font-size: 18px;
  letter-spacing: 0.32em;
  text-decoration: none;
}
nav {
  display: flex;
  gap: 4px;
  overflow-x: auto;
  scrollbar-width: none;
}
.nav-link {
  position: relative;
  padding: 18px 12px;
  font-size: 14px;
  color: var(--ink-2);
  text-decoration: none;
  white-space: nowrap;
}
.nav-link:hover {
  color: var(--ink);
}
.nav-link.active {
  color: var(--ink);
  font-weight: 700;
}
.nav-link.active::after {
  content: "";
  position: absolute;
  left: 12px;
  right: 12px;
  bottom: -1px;
  height: 2px;
  background: var(--ink);
}
@media (max-width: 720px) {
  .inner {
    padding: 0 16px;
    gap: 16px;
  }
  .wordmark {
    font-size: 15px;
    letter-spacing: 0.2em;
  }
  .nav-link {
    padding: 18px 8px;
    font-size: 13px;
  }
}
</style>
