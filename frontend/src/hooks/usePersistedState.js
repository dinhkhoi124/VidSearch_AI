// src/hooks/usePersistedState.js
import { useEffect, useState } from "react";

/**
 * Giống useState nhưng tự lưu/đọc localStorage theo `key`,
 * để lựa chọn của người dùng (toggle, model, ...) sống sót qua refresh.
 */
export function usePersistedState(key, defaultValue) {
  const [value, setValue] = useState(() => {
    try {
      const stored = localStorage.getItem(key);
      return stored !== null ? JSON.parse(stored) : defaultValue;
    } catch {
      return defaultValue;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // localStorage đầy hoặc bị chặn (private mode) -> bỏ qua, state vẫn chạy bình thường
    }
  }, [key, value]);

  return [value, setValue];
}
