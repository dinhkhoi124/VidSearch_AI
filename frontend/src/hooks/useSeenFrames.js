// src/hooks/useSeenFrames.js
// Theo dõi các frame đã "xem" (mở video / phóng to) trong phiên hiện tại,
// để làm mờ và có thể ẩn khi duyệt kết quả. Persist localStorage.
import { useCallback, useEffect, useState } from "react";

const KEY = "aic.seen";

function load() {
  try {
    const raw = localStorage.getItem(KEY);
    return new Set(raw ? JSON.parse(raw) : []);
  } catch {
    return new Set();
  }
}

export function useSeenFrames() {
  const [seen, setSeen] = useState(load);

  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(Array.from(seen)));
    } catch {
      // bỏ qua
    }
  }, [seen]);

  const markSeen = useCallback((id) => {
    if (id == null) return;
    setSeen((prev) => {
      if (prev.has(id)) return prev;
      const next = new Set(prev);
      next.add(id);
      return next;
    });
  }, []);

  const isSeen = useCallback((id) => seen.has(id), [seen]);
  const clearSeen = useCallback(() => setSeen(new Set()), []);

  return { markSeen, isSeen, clearSeen, seenCount: seen.size };
}
