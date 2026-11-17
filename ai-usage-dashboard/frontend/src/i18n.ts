import { useSyncExternalStore } from 'react';
import english from './locales/en.json';
import japanese from './locales/ja.json';

export const languages = { 'zh-CN': '简体中文', ja: '日本語', en: 'English' } as const;
export type Language = keyof typeof languages;
const storageKey = 'usage-dashboard.language';
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

let language = readLanguage();
const listeners = new Set<() => void>();
if (typeof document !== 'undefined') document.documentElement.lang = language;

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function currentLanguage(): Language {
  return language;
}

export function useLanguage(): Language {
  return useSyncExternalStore(subscribe, currentLanguage);
}

export function changeLanguage(value: string) {
  if (value !== 'zh-CN' && value !== 'ja' && value !== 'en') return;
  if (value === language) return;
  language = value;
  document.documentElement.lang = value;
  document.title = t('AI 使用记录');
  try {
    localStorage.setItem(storageKey, value);
  } catch {
    // Keep the active language even when the browser cannot save it.
  }
  listeners.forEach(listener => listener());
}

export function t(source: string, ...values: unknown[]): string {
  const translated = language !== 'zh-CN' && Object.hasOwn(messages[language], source) ? messages[language][source]! : source;
  return translated.replace(/\{(\d+)\}/g, (match, index) =>
    Number(index) < values.length ? String(values[Number(index)]) : match
  );
}

if (typeof document !== 'undefined') document.title = t('AI 使用记录');
