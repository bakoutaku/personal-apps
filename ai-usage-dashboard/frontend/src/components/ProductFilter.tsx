import { t as translate, useLanguage } from "../i18n";
import { PRODUCTS_BY_PROVIDER, type Product, type Provider, type Source } from '../api/types';
import { productName } from '../domain/quota';
import { productStatus } from '../domain/sources';
import { StatusDot } from './common';

interface Props {
  provider: Provider;
  selected: Product[] | null;
  sources: Source[];
  onChange: (next: Product[] | null) => void;
}

export function ProductFilter({ provider, selected, sources, onChange }: Props) {
  useLanguage();
  const all = PRODUCTS_BY_PROVIDER[provider];
  const toggle = (p: Product) => {
    const cur = new Set(selected ?? []);
    if (cur.has(p)) cur.delete(p);
    else cur.add(p);
    const next = all.filter((x) => cur.has(x));
    onChange(next.length === 0 || next.length === all.length ? null : next);
  };

  return (
    <div className="filters" role="group" aria-label={translate("产品筛选")}>
      <span className="eyebrow" style={{ marginRight: 6 }}>
        {translate("产品")}
      </span>
      <button type="button" className="chip" aria-pressed={selected === null} onClick={() => onChange(null)}>
        {translate("全部")}
      </button>
      {all.map((p) => {
        const { status, localOnly } = productStatus(sources, p);
        const dot = status === 'available' ? (localOnly ? 'part' : 'ok') : status === 'error' ? 'err' : 'off';
        const note =
          status === 'available'
            ? localOnly
              ? translate("仅本机")
              : null
            : status === 'error'
              ? translate("同步失败")
              : status === 'disabled'
                ? translate("已停用")
                : status === 'not_configured'
                  ? translate("未配置")
                  : translate("无来源");
        return (
          <button key={p} type="button" className="chip" aria-pressed={selected?.includes(p) ?? false} onClick={() => toggle(p)}>
            <StatusDot kind={dot} />
            {productName(p)}
            {note && <span className="chip-note">{note}</span>}
          </button>
        );
      })}
      <span className="small subtle">{translate("产品筛选只作用于用量、会话和明细；额度按池显示。")}</span>
    </div>
  );
}
