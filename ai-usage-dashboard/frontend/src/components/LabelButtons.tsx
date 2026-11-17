import { t as translate, useLanguage } from "../i18n";
import { useLabelEditing, type EditorRequest } from './labelEditing';

/** “＋ 添加标签 / ＋ 标签”入口；mock 或未就绪时禁用并说明原因。 */
export function AddLabelButton({ request, children = translate("＋ 添加标签"), small = false }: { request: EditorRequest; children?: React.ReactNode; small?: boolean }) {
  useLanguage();
  const ed = useLabelEditing();
  return (
    <button
      type="button"
      className={small ? 'add-label small' : 'add-label'}
      disabled={!ed.writable}
      title={ed.writable ? undefined : ed.readOnlyReason}
      onClick={() => ed.open(request)}
    >
      {children}
    </button>
  );
}
