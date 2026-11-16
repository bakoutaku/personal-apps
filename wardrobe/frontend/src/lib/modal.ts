// 原生 radio 组只有选中项（没有选中项时为首项）进入 Tab 顺序。
export function tabbable(root: HTMLElement): HTMLElement[] {
  const candidates = [...root.querySelectorAll<HTMLElement>(
    'button, input, select, textarea, a[href], [tabindex]',
  )].filter((el) => {
    if (el.tabIndex < 0 || el.matches(':disabled') || el.closest('[hidden], [inert]')) return false;
    for (let node: HTMLElement | null = el; node; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.display === 'none' || style.visibility === 'hidden') return false;
      if (node === root) break;
    }
    return true;
  });
  return candidates.filter((el) => {
    if (!(el instanceof HTMLInputElement) || el.type !== 'radio' || !el.name) return true;
    const group = candidates.filter((other): other is HTMLInputElement =>
      other instanceof HTMLInputElement && other.type === 'radio' && other.name === el.name && other.form === el.form,
    );
    return el === (group.find((radio) => radio.checked) ?? group[0]);
  });
}

export function inertOutside(root: HTMLElement): () => void {
  const changed: HTMLElement[] = [];
  for (let branch: HTMLElement = root; branch.parentElement; branch = branch.parentElement) {
    for (const sibling of branch.parentElement.children) {
      // 遮罩仍接受关闭抽屉的点击；它自身不可聚焦。
      if (!(sibling instanceof HTMLElement) || sibling === branch || sibling.classList.contains('scrim') || sibling.hasAttribute('inert')) continue;
      sibling.setAttribute('inert', '');
      changed.push(sibling);
    }
    if (branch.parentElement === document.body) break;
  }
  return () => changed.forEach((el) => el.removeAttribute('inert'));
}
