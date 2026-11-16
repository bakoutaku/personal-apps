import registry from '../../../contracts/coverage-reasons.json';
import { describe, expect, it } from 'vitest';
import { isKnownReason, reasonText, REASON_TEXT, UNKNOWN_REASON_TEXT } from './sources';

describe('覆盖原因代码表（contracts/coverage-reasons.json）', () => {
  it('契约表里的每个代码都有中文，文字与表一致', () => {
    for (const [code, entry] of Object.entries(registry.reasons)) {
      expect(reasonText(code), code).toBe(entry.display_text);
    }
  });

  it('前端没有契约表以外的映射', () => {
    expect(Object.keys(REASON_TEXT).sort()).toEqual(Object.keys(registry.reasons).sort());
  });

  it('未知代码显示兜底文字，与契约约定一致，不回显原始代码', () => {
    expect(UNKNOWN_REASON_TEXT).toBe(registry.unknown_display_text);
    expect(isKnownReason('some_future_reason')).toBe(false);
    expect(reasonText('some_future_reason')).toBe('未识别的覆盖原因');
    expect(reasonText('toString')).toBe('未识别的覆盖原因');
  });
});
