import { ref } from 'vue';
import english from './locales/en.json';
import japanese from './locales/ja.json';

export const languages = { 'zh-CN': '简体中文', ja: '日本語', en: 'English' } as const;
type Language = keyof typeof languages;
const storageKey = 'wardrobe.language';
const messages: Record<Exclude<Language, 'zh-CN'>, Record<string, string>> = { en: english, ja: japanese };

function readLanguage(): Language {
  try {
    const saved = localStorage.getItem(storageKey);
    if (saved === 'ja' || saved === 'en') return saved;
  } catch {
    // The interface still works when storage is unavailable.
  }
  return 'zh-CN';
}

export const language = ref<Language>(readLanguage());

export function changeLanguage(value: string) {
  if (value !== 'zh-CN' && value !== 'ja' && value !== 'en') return;
  language.value = value;
  document.documentElement.lang = value;
  try {
    localStorage.setItem(storageKey, value);
  } catch {
    // Keep the active language even when the browser cannot save it.
  }
}

export function t(source: string, ...values: unknown[]): string {
  const active = language.value;
  const translated = active !== 'zh-CN' && Object.hasOwn(messages[active], source) ? messages[active][source]! : source;
  return translated.replace(/\{(\d+)\}/g, (match, index) =>
    Number(index) < values.length ? String(values[Number(index)]) : match
  );
}

if (typeof document !== 'undefined') {
  document.documentElement.lang = language.value;
}
