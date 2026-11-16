<script setup lang="ts">
// 一条购买明细的输入字段（新建购买、追加明细、编辑明细共用）。
import { ref } from "vue";
import type { Product } from "../api/types";
import { SIZE_SYSTEM_LABELS } from "../lib/labels";
import type { LineDraft } from "../lib/purchaseLine";
import ProductPicker from "./ProductPicker.vue";

// 布尔 prop 省略时 Vue 会当作 false，因此必须显式给默认值
const props = withDefaults(defineProps<{ modelValue: LineDraft; errors?: Record<string, string>; prefix?: string; allowProduct?: boolean }>(), {
  errors: () => ({}),
  prefix: "",
  allowProduct: true,
});
const picking = ref(false);

function pick(p: Product) {
  props.modelValue.product_id = p.id;
  props.modelValue.product_name = p.name_ja || p.name_zh || p.name_en || `商品 ${p.id}`;
  picking.value = false;
}
const e = (k: string) => props.errors?.[`${props.prefix ?? ""}${k}`];
</script>

<template>
  <div class="line-form">
    <div v-if="allowProduct" class="product-row">
      <span class="muted">对应商品：</span>
      <strong v-if="modelValue.product_id">{{ modelValue.product_name || `商品 ${modelValue.product_id}` }}</strong>
      <span v-else class="muted">未指定（可以稍后匹配）</span>
      <button type="button" class="link-btn" :aria-expanded="picking" @click="picking = !picking">{{ picking ? "收起" : "选择商品" }}</button>
      <button v-if="modelValue.product_id" type="button" class="link-btn" @click="modelValue.product_id = null; modelValue.product_name = ''">清除</button>
    </div>
    <ProductPicker v-if="picking" :selected-id="modelValue.product_id" @select="pick" />
    <div class="form-grid">
      <label class="field"><span>小票编号</span><input v-model="modelValue.item_code_raw" /></label>
      <label class="field"><span>小票名称</span><input v-model="modelValue.name_raw" /></label>
      <label class="field"><span>颜色编号</span><input v-model="modelValue.color_code" /></label>
      <label class="field"><span>颜色名称</span><input v-model="modelValue.color_name" /></label>
      <label class="field">
        <span>颜色值</span><input v-model="modelValue.color_hex" placeholder="#1F2A44" :aria-invalid="!!e('color_hex')" />
        <span v-if="e('color_hex')" class="field-error">{{ e("color_hex") }}</span>
      </label>
      <label class="field"><span>尺码</span><input v-model="modelValue.size_label" /></label>
      <label class="field">
        <span>尺码体系</span>
        <select v-model="modelValue.size_system">
          <option value="">—</option>
          <option v-for="(t, k) in SIZE_SYSTEM_LABELS" :key="k" :value="k">{{ t }}</option>
        </select>
      </label>
      <label class="field">
        <span>数量</span><input v-model="modelValue.quantity" type="number" min="1" max="99" :aria-invalid="!!e('quantity')" />
        <span v-if="e('quantity')" class="field-error">{{ e("quantity") }}</span>
      </label>
      <label class="field"><span>单价</span><input v-model="modelValue.unit_price" type="number" min="0" inputmode="numeric" /></label>
      <label class="field"><span>折扣金额</span><input v-model="modelValue.discount_amount" type="number" min="0" inputmode="numeric" /></label>
      <label class="field wide"><span>备注</span><input v-model="modelValue.notes" /></label>
    </div>
  </div>
</template>

<style scoped>
.line-form {
  display: grid;
  gap: 12px;
}
.product-row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  align-items: baseline;
  font-size: 14px;
  overflow-wrap: anywhere;
}
</style>
