// src/hooks/useQueryHistory.js
// Lưu lịch sử truy vấn (persist localStorage) để chạy lại nhanh khi thi.
// Mỗi mục: { id, mode, query, ts }. Chống trùng liên tiếp cùng mode+query.
import { useCallback, useEffect, useState } from "react";

const KEY = "aic.history";
const MAX = 50;

function load() {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export function useQueryHistory() {
  const [history, setHistory] = useState(load);

  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(history));
    } catch {
      // bỏ qua
    }
  }, [history]);

  const push = useCallback((mode, query) => {
    const q = (query || "").trim();
    if (!q) return;
    setHistory((prev) => {
      if (prev[0] && prev[0].mode === mode && prev[0].query === q) return prev;
      const entry = { id: Date.now(), mode, query: q, ts: Date.now() };
      return [entry, ...prev].slice(0, MAX);
    });
  }, []);

  const clear = useCallback(() => setHistory([]), []);

  return { history, push, clear };
}
