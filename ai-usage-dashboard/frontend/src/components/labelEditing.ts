import { createContext, useContext } from 'react';

/** 打开标签编辑器的请求。 */
export type EditorRequest =
  | { mode: 'create-range'; from: string; to: string }
  | { mode: 'create-session'; sessionId: string }
  | { mode: 'edit'; labelId: string };

export interface LabelEditing {
  /** live 且已配对时为 true；mock 只读 */
  writable: boolean;
  /** 不可写时给按钮的说明 */
  readOnlyReason: string;
  open: (req: EditorRequest) => void;
}

export const LabelEditingContext = createContext<LabelEditing>({
  writable: false,
  readOnlyReason: '模拟数据只读，接入本机服务后可编辑标签',
  open: () => {},
});

export function useLabelEditing(): LabelEditing {
  return useContext(LabelEditingContext);
}
