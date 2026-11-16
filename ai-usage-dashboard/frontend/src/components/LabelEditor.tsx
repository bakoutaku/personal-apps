// 标签新建 / 改名 / 删除（右侧抽屉）。写入规则见 api/labelWriter.ts 与 docs/label-editing-handoff.md。
import { useEffect, useRef, useState } from 'react';
import { explicitProducts, NAME_MAX, nameLength, validateName, type LabelWriter, type WriteOutcome } from '../api/labelWriter';
import { PRODUCTS_BY_PROVIDER, type Label, type Product, type Provider, type Session, type Source } from '../api/types';
import { productName } from '../domain/quota';
import { fmtDateTimeRel, fmtRangeLabel } from '../time/tz';
import type { Clock } from './common';
import type { EditorRequest } from './labelEditing';

interface Props {
  request: EditorRequest;
  writer: LabelWriter;
  provider: Provider;
  accountId: string;
  /** 当前产品筛选（null = 全部） */
  products: Product[] | null;
  sources: Source[];
  /** 当前整屏读到的标签与会话（编辑时按 id 找最新 revision） */
  labels: Label[];
  sessions: Session[];
  clock: Clock;
  /** 写入成功：关闭并整屏重读 */
  onDone: () => void;
  /** 不关闭，重读整屏（冲突 / 未确认时核对） */
  onRefresh: () => void;
  onClose: () => void;
  /** 本应用会话失效：回到配对（草稿留在 writer 内存里） */
  onUnauthorized: () => void;
}

type Msg = { tone: 'error' | 'warn' | 'info'; text: string } | null;

function outcomeMessage(r: WriteOutcome & { ok: false }, op: 'create' | 'rename' | 'delete'): Msg {
  switch (r.kind) {
    case 'unconfirmed':
      return op === 'create'
        ? { tone: 'warn', text: '没有收到服务的回应，不能确定是否已保存。可以用同一请求再确认一次（不会重复创建），或放弃后重新读取列表核对。' }
        : { tone: 'warn', text: '没有收到服务的回应，不能确定是否已生效。已重新读取列表，请核对后再决定是否重新提交。' };
    case 'unauthorized':
      return { tone: 'error', text: '本机会话已失效，需要重新配对。草稿会保留，配对后可以继续。' };
    case 'csrf_invalid':
      return r.restored
        ? { tone: 'warn', text: '这次写入没有通过校验，已恢复本机会话。请再点一次提交。' }
        : { tone: 'error', text: '这次写入没有通过校验，且未能恢复本机会话，请重新配对。' };
    case 'forbidden':
      return { tone: 'error', text: '服务拒绝了这个页面的来源，请检查本机连接配置（开发时需要 --dev-origin）。' };
    case 'not_found':
      return op === 'delete'
        ? { tone: 'info', text: '这个标签当前已不存在。已重新读取列表。' }
        : { tone: 'error', text: '没有找到这个标签或关联的会话，可能已被修改、删除或不在当前范围内。已重新读取列表。' };
    case 'idempotency_conflict':
      return { tone: 'error', text: '这次创建与之前的请求冲突（同一个请求已用于其他内容或已删除的标签）。已重新读取列表，请先核对现有标签，再决定是否重新创建。' };
    case 'revision_conflict':
      return { tone: 'warn', text: '标签已在别处修改。已重新读取，请确认最新内容后再提交。' };
    case 'invalid':
      return { tone: 'error', text: `内容不被接受：${r.fields.map((f) => f.field || f.reason).filter(Boolean).join('、') || '请检查名称和关联范围'}` };
    case 'precondition_required':
      return { tone: 'error', text: '写入请求缺少版本信息（前端问题），没有保存。' };
    case 'rate_limited':
      return { tone: 'warn', text: r.retryAfterSeconds ? `请求过于频繁，请约 ${Math.ceil(r.retryAfterSeconds)} 秒后再试。` : '请求过于频繁，请稍后再试。' };
    default:
      return { tone: 'error', text: `保存失败（HTTP ${r.status} · ${r.code}）。` };
  }
}

export function LabelEditor(props: Props) {
  const { request, writer, provider, accountId, sources, labels, sessions, clock } = props;
  const all = PRODUCTS_BY_PROVIDER[provider];
  const editing = request.mode === 'edit' ? labels.find((l) => l.id === request.labelId) ?? null : null;
  const pending = writer.pending;
  const locked = request.mode !== 'edit' && !!pending?.unconfirmed;

  // 会话失效后恢复的草稿（同一个编辑请求才用）
  const [resumed] = useState(() => {
    const r = writer.resume;
    return r && JSON.stringify(r.request) === JSON.stringify(request) ? r : null;
  });
  const [name, setName] = useState(() => (locked ? pending!.body.name : resumed ? resumed.name : editing?.name ?? ''));
  const [products, setProducts] = useState<Product[]>(() => resumed?.products ?? explicitProducts(props.products, all));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<Msg>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);
  const opener = useRef<Element | null>(null);

  useEffect(() => {
    opener.current = document.activeElement;
    nameRef.current?.focus();
    return () => (opener.current as HTMLElement | null)?.focus?.();
  }, []);

  // 草稿随输入写进 writer 内存：自动刷新途中会话失效（401）卸载页面时，重新配对后能恢复；不会自动提交
  useEffect(() => {
    writer.resume = { request, name, products };
  }, [writer, request, name, products]);

  const dirty = request.mode === 'edit' ? name.trim() !== (editing?.name ?? '') : name.trim() !== '';
  const close = () => {
    if (busy) return;
    if (dirty && !locked && !window.confirm('有未保存的内容，确定关闭吗？')) return;
    props.onClose();
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && close();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const handle = (r: WriteOutcome, op: 'create' | 'rename' | 'delete') => {
    if (r.ok) {
      props.onDone();
      return;
    }
    setMsg(outcomeMessage(r, op));
    if (r.kind === 'unauthorized') {
      // 草稿留在内存里，重新配对后恢复
      writer.resume = { request, name, products };
      props.onUnauthorized();
    }
    // 冲突 / 未找到 / 未确认的改名删除：重读整屏核对，草稿留在表单里
    if (r.kind === 'revision_conflict' || r.kind === 'not_found' || r.kind === 'idempotency_conflict' || (r.kind === 'unconfirmed' && op !== 'create')) {
      props.onRefresh();
    }
    if (op === 'delete' && r.kind === 'not_found') props.onDone();
  };

  const nameError = validateName(name);
  const productError = request.mode === 'create-range' && products.length === 0 ? '至少选择一个产品。' : null;

  const submitCreate = async () => {
    if (!locked) {
      if (nameError || productError) return;
      const target =
        request.mode === 'create-range'
          ? { kind: 'range' as const, from: request.from, to: request.to, products }
          : { kind: 'session' as const, session_id: (request as { sessionId: string }).sessionId };
      writer.beginCreate({ provider, account_id: accountId, name: name.trim(), target });
    }
    setBusy(true);
    setMsg(null);
    try {
      handle(await writer.submitCreate(), 'create');
    } finally {
      setBusy(false);
    }
  };

  const submitRename = async () => {
    if (!editing || nameError || name.trim() === editing.name) return;
    setBusy(true);
    setMsg(null);
    try {
      handle(await writer.rename(editing.id, editing.revision, name.trim()), 'rename');
    } finally {
      setBusy(false);
    }
  };

  const submitDelete = async () => {
    if (!editing) return;
    setBusy(true);
    setMsg(null);
    try {
      handle(await writer.remove(editing.id, editing.revision), 'delete');
    } finally {
      setBusy(false);
      setConfirmDelete(false);
    }
  };

  const abandonPending = () => {
    writer.discardCreate();
    props.onRefresh();
    props.onClose();
  };

  // 目标说明
  let targetText: React.ReactNode = null;
  const describeSession = (id: string) => {
    const s = sessions.find((x) => x.id === id);
    return s
      ? `${productName(s.product)} · 会话 ${s.id.slice(0, 12)}… · 大致记录范围 ${fmtDateTimeRel(s.first_record_in_range_at, clock.asOfMs, clock.tz)}–${fmtDateTimeRel(s.last_record_in_range_at, clock.asOfMs, clock.tz)}`
      : `会话 ${id}`;
  };
  if (request.mode === 'create-range') targetText = `时间段 ${fmtRangeLabel(request.from, request.to, clock.tz)}`;
  else if (request.mode === 'create-session') targetText = describeSession(request.sessionId);
  else if (editing) {
    const t = editing.target;
    targetText =
      t.kind === 'range'
        ? `时间段 ${t.to === null ? `${fmtDateTimeRel(t.from, clock.asOfMs, clock.tz)} – 进行中` : fmtRangeLabel(t.from, t.to, clock.tz)} · ${t.products.map(productName).join(' / ')}`
        : describeSession(t.session_id);
  }

  const title = request.mode === 'edit' ? '编辑标签' : request.mode === 'create-session' ? '给会话添加标签' : '给时间段添加标签';
  const connected = (p: Product) => sources.some((s) => s.product === p && (s.connection_status === 'available' || s.connection_status === 'error'));

  return (
    <div className="drawer-backdrop" onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <form
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="label-editor-h"
        onSubmit={(e) => {
          e.preventDefault();
          void (request.mode === 'edit' ? submitRename() : submitCreate());
        }}
      >
        <div className="drawer-head">
          <h2 id="label-editor-h">{title}</h2>
          <button type="button" className="ibtn" aria-label="关闭" onClick={close} disabled={busy}>
            ✕
          </button>
        </div>

        {request.mode === 'edit' && !editing ? (
          <p className="notice">这个标签已修改或已移出当前范围，当前列表里找不到它。可以关闭后在其他范围查看，这里不会重新创建。</p>
        ) : (
          <>
            <div className="field">
              <span className="eyebrow">关联</span>
              <div className="field-value">{targetText}</div>
            </div>

            <label className="field">
              <span className="eyebrow">名称</span>
              <input
                ref={nameRef}
                className="code-input"
                value={name}
                maxLength={NAME_MAX * 4}
                onChange={(e) => setName(e.target.value)}
                disabled={busy || locked}
                aria-invalid={name !== '' && !!nameError}
                aria-describedby="label-name-hint"
                autoComplete="off"
              />
              <span id="label-name-hint" className={`small ${name !== '' && nameError ? 'field-error' : 'muted'}`}>
                {name !== '' && nameError ? nameError : `${nameLength(name)} / ${NAME_MAX}`}
              </span>
            </label>

            {request.mode === 'create-range' && (
              <fieldset className="field" disabled={busy || locked}>
                <legend className="eyebrow">产品</legend>
                <div className="check-row">
                  {all.map((p) => (
                    <label key={p} className="check">
                      <input
                        type="checkbox"
                        checked={products.includes(p)}
                        onChange={(e) => setProducts(e.target.checked ? all.filter((x) => x === p || products.includes(x)) : products.filter((x) => x !== p))}
                      />
                      {productName(p)}
                      {!connected(p) && <span className="small muted">（未接入，目前不会匹配到记录）</span>}
                    </label>
                  ))}
                </div>
                {productError && <span className="small field-error">{productError}</span>}
              </fieldset>
            )}

            {editing?.target.kind === 'range' && editing.target.to === null && (
              <p className="small muted" style={{ margin: 0 }}>
                这是“进行中”的标签，改名不会改变它的结束时间。
              </p>
            )}

            <p className="small muted" style={{ margin: 0, lineHeight: 1.7 }}>
              标签只说明“这段在做什么”，按时间或会话关联记录，不是精确的额度消耗。标签可重叠；按标签汇总时同一条记录只计一次，各标签小计不能相加。
            </p>

            {msg && (
              <p className={`notice ${msg.tone === 'error' ? 'error' : msg.tone === 'warn' ? 'warn-notice' : ''}`} role="alert" style={{ margin: 0 }}>
                {msg.text}
              </p>
            )}

            {editing && msg && (
              <p className="small muted" style={{ margin: 0 }}>
                服务端当前：{editing.name}（版本 {editing.revision}）
              </p>
            )}

            <div className="drawer-actions">
              {request.mode === 'edit' ? (
                <>
                  <button type="submit" className="btn-primary" disabled={busy || !!nameError || name.trim() === editing?.name}>
                    {busy ? '正在保存…' : '保存名称'}
                  </button>
                  {!confirmDelete ? (
                    <button type="button" className="text-btn danger-btn" onClick={() => setConfirmDelete(true)} disabled={busy}>
                      删除标签
                    </button>
                  ) : (
                    <span className="confirm-row">
                      <span className="small">只删除这个标签，不会删除任何用量记录。</span>
                      <button type="button" className="text-btn danger-btn" onClick={() => void submitDelete()} disabled={busy}>
                        确认删除
                      </button>
                      <button type="button" className="text-btn" onClick={() => setConfirmDelete(false)} disabled={busy}>
                        取消
                      </button>
                    </span>
                  )}
                </>
              ) : locked ? (
                <>
                  <button type="submit" className="btn-primary" disabled={busy}>
                    {busy ? '正在确认…' : '用同一请求再确认'}
                  </button>
                  <button type="button" className="text-btn" onClick={abandonPending} disabled={busy}>
                    放弃并重新读取列表
                  </button>
                </>
              ) : (
                <button type="submit" className="btn-primary" disabled={busy || !!nameError || !!productError}>
                  {busy ? '正在保存…' : '保存标签'}
                </button>
              )}
            </div>
          </>
        )}
      </form>
    </div>
  );
}
