// src/components/LlmQuotaBanner.jsx
// Cảnh báo "key LLM hết lượt truy cập" — dải ngang dưới thanh tiêu đề.
//
// Vì sao cần: hết quota Gemini KHÔNG làm hỏng request nào cả. Query expansion
// trả None (query tiếng Việt đi thẳng vào backbone vốn thiên tiếng Anh), planner
// rơi về "câu cuối = query", QA trả câu xin lỗi. Kết quả chỉ đơn giản là kém đi
// — giữa buổi thi thì đó là kiểu hỏng tệ nhất: im lặng. Dải này nói rõ đang
// hỏng ở đâu và còn đường lui nào.
//
// Trạng thái đến từ header của mọi response (xem api/llmStatus.js), nên banner
// tự bật/tắt theo thao tác bình thường của người dùng.
import { useEffect, useState } from "react";
import { useLlmStatus } from "../hooks/useLlmStatus";
import { AlertTriangleIcon, CloseIcon, RefreshIcon } from "./Icons";

const PROVIDER_LABEL = {
  gemini: "Gemini",
  openai: "LLM dự phòng (OpenAI-compatible)",
};

const SCOPE_LABEL = {
  day: "hết hạn mức theo NGÀY — chỉ hồi lại khi Google reset quota (0h Thái Bình Dương)",
  minute: "vượt giới hạn số request mỗi phút — đợi một lát là gọi lại được",
  unknown: "bị Google chặn vì vượt hạn mức",
};

function LlmQuotaBanner({ onOpenSettings }) {
  const { status, checking, refresh } = useLlmStatus();
  // Tắt banner theo TỪNG sự cố (since), không tắt vĩnh viễn: hết quota lần sau
  // — hoặc provider khác gãy — vẫn phải hiện lại.
  const [dismissed, setDismissed] = useState(0);

  useEffect(() => {
    if (!status.exhausted) setDismissed(0);
  }, [status.exhausted]);

  if (!status.exhausted || dismissed === status.since) return null;

  const provider = PROVIDER_LABEL[status.provider] || status.provider;
  const scope = SCOPE_LABEL[status.scope] || SCOPE_LABEL.unknown;

  return (
    <div
      role="status"
      className="flex items-start gap-3 px-3 sm:px-4 py-2.5 bg-amber-50 border-b border-amber-200 text-amber-900 shrink-0"
    >
      <AlertTriangleIcon className="w-5 h-5 shrink-0 mt-0.5 text-amber-600" />

      <div className="flex-1 min-w-0 text-[13px] leading-relaxed">
        <span className="font-semibold">
          Key {provider} hết lượt truy cập
          {status.model ? ` (${status.model})` : ""} — {scope}.
        </span>{" "}
        {status.fallback ? (
          <span>
            Hệ đang tự chuyển sang provider còn lại, kết quả có thể khác thường ngày.
          </span>
        ) : (
          <span>
            Không còn provider dự phòng: query giữ nguyên tiếng Việt (không dịch/mở
            rộng), Agent rơi về tin nhắn cuối làm query, Hỏi-đáp không trả lời được.
            Đổi <code className="font-mono text-[12px]">GEMINI_API_KEY</code> hoặc cấu
            hình endpoint OpenAI-compatible để chạy tiếp.
          </span>
        )}
        {status.retryAfter ? (
          <span className="text-amber-700"> Google gợi ý thử lại sau ~{Math.round(status.retryAfter)}s.</span>
        ) : null}
        {status.count > 1 ? (
          <span className="text-amber-700"> ({status.count} lần liên tiếp)</span>
        ) : null}
        {status.detail ? (
          <span className="block mt-0.5 text-[11px] text-amber-700/80 truncate" title={status.detail}>
            {status.detail}
          </span>
        ) : null}
      </div>

      {onOpenSettings && status.provider === "gemini" && (
        <button
          onClick={onOpenSettings}
          title="Mở Cài đặt để dán key Gemini khác"
          className="shrink-0 px-2 py-1 rounded-md text-xs font-semibold bg-amber-600 text-white hover:bg-amber-700 transition-colors"
        >
          Đổi key
        </button>
      )}
      <button
        onClick={refresh}
        disabled={checking}
        title="Gọi lại /agent/llm_status để xem key đã hồi chưa"
        className="shrink-0 inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-semibold text-amber-800 hover:bg-amber-100 disabled:opacity-50 transition-colors"
      >
        <RefreshIcon className={`w-3.5 h-3.5 ${checking ? "animate-spin" : ""}`} />
        <span className="hidden sm:inline">Kiểm tra lại</span>
      </button>
      <button
        onClick={() => setDismissed(status.since)}
        title="Ẩn cảnh báo này"
        className="shrink-0 p-1 rounded-md text-amber-700 hover:bg-amber-100 transition-colors"
      >
        <CloseIcon className="w-4 h-4" />
      </button>
    </div>
  );
}

export default LlmQuotaBanner;
