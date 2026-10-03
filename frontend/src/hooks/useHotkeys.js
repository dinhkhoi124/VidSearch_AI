// src/hooks/useHotkeys.js
// Đăng ký một handler keydown toàn cục. SearchPage tự quyết định phím nào làm gì
// (giữ mọi state ở một chỗ). Cung cấp helper isEditableTarget để bỏ qua phím
// khi người dùng đang gõ trong ô nhập.
import { useEffect } from "react";

export function isEditableTarget(e) {
  const el = e.target;
  if (!el) return false;
  const tag = el.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    el.isContentEditable
  );
}

export function useHotkeys(handler, enabled = true) {
  useEffect(() => {
    if (!enabled) return undefined;
    const onKeyDown = (e) => handler(e);
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [handler, enabled]);
}
