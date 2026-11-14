import { getFocusNavController } from "@decky/ui";

type NavNode = { Element?: HTMLElement; TakeFocus?: () => unknown };
type Position = { element: HTMLElement; top: number; left: number };
type Anchor = { element: HTMLElement; node?: NavNode; positions: Position[]; label: string | null };
let root: HTMLElement | null = null;
let menuAnchor: Anchor | null = null;
let inputRevision = 0;
let operation = 0;
const timers = new Set<ReturnType<typeof setTimeout>>();

function activeNode(): NavNode | undefined {
  try {
    const controller = getFocusNavController();
    const context = controller?.GetActiveContext?.() || controller?.m_ActiveContext || controller?.m_LastActiveContext;
    return context?.m_LastActiveFocusNavTree?.GetLastFocusedNode?.();
  } catch { return undefined; }
}
function capture(): Anchor | null {
  if (!root) return null;
  const node = activeNode();
  const focused = node?.Element && root.contains(node.Element) ? node.Element : root.ownerDocument.activeElement as HTMLElement | null;
  if (!focused || !root.contains(focused)) return menuAnchor;
  const positions: Position[] = [];
  for (let parent: HTMLElement | null = focused; parent; parent = parent.parentElement) {
    if (parent.scrollHeight > parent.clientHeight || parent.scrollTop || parent.scrollLeft) {
      positions.push({ element: parent, top: parent.scrollTop, left: parent.scrollLeft });
    }
  }
  return { element: focused, node: node?.Element === focused ? node : undefined,
    positions, label: focused.getAttribute("aria-label") };
}
export function rememberMenuFocus(): void { menuAnchor = capture(); }
export function openMenuWithFocus(open: () => void): void { rememberMenuFocus(); open(); }

export function registerFocusRoot(element: HTMLElement | null): () => void {
  root = element;
  const doc = element?.ownerDocument;
  const noteInput = () => { inputRevision++; };
  const events = ["keydown", "pointerdown", "wheel", "touchstart", "vgp_onbuttondown"];
  events.forEach((event) => doc?.addEventListener(event, noteInput, true));
  return () => {
    events.forEach((event) => doc?.removeEventListener(event, noteInput, true));
    if (root === element) {
      root = null; menuAnchor = null; operation++;
      timers.forEach(clearTimeout); timers.clear();
    }
  };
}

// Retain Steam's gamepad focus as well as the DOM focus. Do not pull focus back after a user moves away.
export function withSettingFocus<A extends unknown[], R>(save: (...args: A) => Promise<R>): (...args: A) => Promise<R> {
  return async (...args: A) => {
    const anchor = capture();
    menuAnchor = null;
    const id = ++operation;
    const revision = inputRevision;
    const boundary = root;
    try { return await save(...args); }
    finally {
      if (anchor && boundary) {
        const restore = () => {
          if (operation !== id || inputRevision !== revision || root !== boundary || !boundary.isConnected) return;
          let target = anchor.element;
          if (!target.isConnected && anchor.label) {
            target = Array.from(boundary.querySelectorAll<HTMLElement>("[aria-label]")).find((e) => e.getAttribute("aria-label") === anchor.label) || target;
          }
          if (!target.isConnected || !boundary.contains(target)) return;
          try {
            if (target === anchor.element) anchor.node?.TakeFocus?.();
          } catch { /* A removed Steam nav node must not break saving. */ }
          try { target.focus({ preventScroll: true }); } catch { /* Detached DOM fallback. */ }
          anchor.positions.forEach((p) => {
            if (p.element.isConnected) { p.element.scrollTop = p.top; p.element.scrollLeft = p.left; }
          });
        };
        // Let the dropdown close and React commit before restoring; Steam's delayed scroll follows a frame later.
        [0, 80, 220].forEach((delay) => {
          const timer = setTimeout(() => { timers.delete(timer); restore(); }, delay);
          timers.add(timer);
        });
      }
    }
  };
}
