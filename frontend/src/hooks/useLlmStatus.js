// src/hooks/useLlmStatus.js
// Trạng thái quota LLM cho giao diện: theo kho dùng chung ở api/llmStatus.js
// (được header của mọi response cập nhật) + một lần fetch lúc mount để banner
// đúng ngay khi mở trang, chưa cần bấm tìm kiếm gì.
import { useCallback, useEffect, useState } from "react";
import { getLlmState, setLlmStatus, subscribeLlmStatus } from "../api/llmStatus";
import { subscribeBaseUrl } from "../api/apiClient";
import { getLlmStatus } from "../api/searchService";

export function useLlmStatus() {
  const [status, setStatus] = useState(getLlmState);
  const [checking, setChecking] = useState(false);

  const refresh = useCallback(async () => {
    setChecking(true);
    try {
      setLlmStatus(await getLlmStatus());
    } catch {
      // Backend chưa lên / bản cũ không có endpoint -> im lặng, header vẫn là
      // đường cập nhật chính.
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    const unsub = subscribeLlmStatus(setStatus);
    refresh();
    // Đổi base URL trong Settings = nói chuyện với backend KHÁC, quota của nó
    // không liên quan gì tới cái vừa hiện.
    const unsubBase = subscribeBaseUrl(() => refresh());
    return () => {
      unsub();
      unsubBase();
    };
  }, [refresh]);

  return { status, checking, refresh };
}
