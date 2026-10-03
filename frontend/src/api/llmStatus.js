// src/api/llmStatus.js
// Kho trạng thái quota LLM dùng chung cho cả app (không phụ thuộc React).
//
// Backend gắn X-Llm-Quota / X-Llm-Quota-Info vào MỌI response (main.py), nên
// interceptor của apiClient chỉ việc đổ header vào đây: banner "key Gemini hết
// lượt" bật lên ngay ở request kế tiếp mà không cần polling. GET
// /agent/llm_status lo trạng thái ban đầu lúc mở trang.
//
// File này cố tình KHÔNG import apiClient — apiClient import ngược lại nó cho
// interceptor, vòng import sẽ vỡ lúc khởi tạo module.

const EMPTY = { exhausted: false };

let state = EMPTY;
const listeners = new Set();

export function getLlmState() {
  return state;
}

export function subscribeLlmStatus(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

// Hai trạng thái coi là "như nhau" khi cùng sự cố (since) của cùng provider —
// không so sâu thì mỗi response lại phát tín hiệu và React render lại vô ích.
function same(a, b) {
  if (a.exhausted !== b.exhausted) return false;
  if (!a.exhausted) return true;
  return a.provider === b.provider && a.since === b.since && a.count === b.count;
}

function set(next) {
  if (same(state, next)) return;
  state = next;
  listeners.forEach((fn) => fn(state));
}

/** Trạng thái đầy đủ từ GET /agent/llm_status. */
export function setLlmStatus(data) {
  if (!data || !data.exhausted) {
    set(EMPTY);
    return;
  }
  set({
    exhausted: true,
    provider: data.provider || "gemini",
    model: data.model || "",
    scope: data.scope || "unknown",
    since: Math.round(Number(data.since) || 0),
    count: Number(data.count) || 1,
    fallback: !!data.fallback,
    retryAfter: data.retry_after_s == null ? null : Number(data.retry_after_s),
    detail: data.detail || "",
  });
}

// "provider=gemini;model=...;scope=day;since=1755..;count=3;fallback=0;retry=41"
function parseInfo(raw) {
  const out = {};
  String(raw || "")
    .split(";")
    .forEach((part) => {
      const i = part.indexOf("=");
      if (i > 0) out[part.slice(0, i)] = part.slice(i + 1);
    });
  return out;
}

/** Đọc header của một response bất kỳ. Header thiếu = backend cũ -> giữ nguyên
 *  trạng thái hiện có thay vì kết luận "mọi thứ ổn". */
export function applyLlmHeaders(headers) {
  const flag = headers?.["x-llm-quota"]; // axios hạ hết tên header về chữ thường
  if (!flag) return;
  if (flag !== "exhausted") {
    set(EMPTY);
    return;
  }
  const info = parseInfo(headers["x-llm-quota-info"]);
  set({
    exhausted: true,
    provider: info.provider || "gemini",
    model: info.model || "",
    scope: info.scope || "unknown",
    since: Number(info.since) || 0,
    count: Number(info.count) || 1,
    fallback: info.fallback === "1",
    retryAfter: info.retry ? Number(info.retry) : null,
    // Header không tải nổi câu lỗi tiếng Anh dài (và chỉ latin-1) — muốn chi
    // tiết thì bấm "Kiểm tra lại", nó gọi /agent/llm_status.
    detail: state.exhausted && state.since === Number(info.since) ? state.detail : "",
  });
}
