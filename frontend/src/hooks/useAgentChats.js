// src/hooks/useAgentChats.js
// Lịch sử tra cứu Agent của RIÊNG mình, lưu ở backend theo member_id
// (xem backend/services/agent_history_store.py).
//
// Vì sao phải có: mỗi lượt /agent/chat là 1..N call LLM (plan, ReAct, QA
// vision). Gõ lại một hướng đã dò để xem lại frame cũ là đốt quota để lấy đúng
// thứ vừa có - mà key cạn quota giữa buổi thi thì cả nhóm đứng hình. Ở đây lưu
// nguyên KẾT QUẢ, nên "xem lại" là 0 request tới /agent/*, 0 token.
//
// GHI đi qua hàng đợi bền vững của roomClient (mất mạng thì nằm chờ trong
// localStorage rồi tự xả), ĐỌC thì gọi thẳng REST - đọc mà offline không có
// nghĩa gì.
import { useCallback, useState } from "react";
import roomClient, { resolveRoomBaseUrl, roomBaseSource } from "../api/roomClient";

const SOURCE_LABEL = {
  settings: "ô Room URL trong Cài đặt ⚙",
  env: "VITE_ROOM_BASE_URL trong frontend/.env",
  backend: "đang ăn theo Backend URL",
};

/**
 * Vì sao không dùng một câu "không lấy được lịch sử" cho mọi lỗi: ba nguyên nhân
 * hay gặp cần ba hành động KHÁC nhau, mà URL phòng lại đến từ ba nguồn sửa ở ba
 * chỗ khác nhau (xem roomBaseSource trong api/roomClient.js). Không in ra ĐANG
 * GỌI VÀO ĐÂU và VÌ SAO thì người đọc chỉ biết là hỏng.
 */
function historyError(err) {
  const url = resolveRoomBaseUrl();
  const where = SOURCE_LABEL[roomBaseSource()] || roomBaseSource();
  const at = `${url} (${where})`;

  if (err.code === "ERR_NETWORK") {
    return `Không nối được máy chủ phòng ${at}. Chỗ đó chưa bật, hoặc URL đã cũ — `
      + "sửa Room URL trong Cài đặt ⚙ để trỏ về backend đang chạy.";
  }
  if (err.code === "ECONNABORTED" || /timeout/i.test(err.message || "")) {
    return `Máy chủ phòng ${at} chưa trả lời. Nếu vừa bật server thì nó còn đang nạp model — thử lại sau ít giây.`;
  }
  if (err.response?.status === 404) {
    return `Server ở ${at} chưa có endpoint lịch sử Agent — nó đang chạy bản CŨ, khởi động lại là xong.`;
  }
  // 503 = phòng tắt (ROOM_ENABLED=false) hoặc tiến trình khác đang giữ state.
  // Backend đã viết sẵn câu giải thích, đừng nuốt mất nó.
  return err.response?.data?.detail || `${err.message || "Lỗi không rõ"} khi gọi ${at}.`;
}

export function useAgentChats(active) {
  const [chats, setChats] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  /** Nạp danh sách cuộc trò chuyện (KHÔNG kèm frame - xem _chat_summary bên BE). */
  const refresh = useCallback(async () => {
    if (!active) {
      setChats([]);
      return;
    }
    setLoading(true);
    setError("");
    try {
      setChats(await roomClient.fetchAgentChats());
    } catch (err) {
      // Không nối được phòng KHÔNG phải lỗi chặn đường: panel vẫn tìm kiếm bình
      // thường, chỉ là chưa xem được lịch sử cũ.
      setError(historyError(err));
    } finally {
      setLoading(false);
    }
  }, [active]);

  /** Mở một cuộc, KÈM frame của từng lượt. Trả null nếu không lấy được. */
  const loadChat = useCallback(
    async (chatId) => {
      if (!active || !chatId) return null;
      try {
        return await roomClient.fetchAgentChat(chatId);
      } catch {
        return null;
      }
    },
    [active]
  );

  /**
   * Lưu MỘT lượt vừa chạy xong. Cập nhật chỉ mục tại chỗ luôn (lạc quan): người
   * dùng mở tab Lịch sử ngay sau đó phải thấy cuộc vừa chạy, không phải đợi một
   * vòng REST nữa.
   */
  const saveTurn = useCallback(
    (chatId, title, turn) => {
      if (!active || !chatId || !turn?.id) return;
      roomClient.sendAgentTurn({ chat_id: chatId, title, turn });
      setChats((prev) => {
        const now = Date.now();
        const found = prev.find((c) => c.id === chatId);
        const next = found
          ? {
              ...found,
              updated_at: now,
              turn_count: found.turn_count + 1,
              result_count: found.result_count + (turn.results?.length || turn.videos?.length || 0),
              last_question: turn.question,
            }
          : {
              id: chatId,
              title: title || turn.question || "",
              created_at: now,
              updated_at: now,
              turn_count: 1,
              result_count: turn.results?.length || turn.videos?.length || 0,
              last_question: turn.question,
            };
        return [next, ...prev.filter((c) => c.id !== chatId)];
      });
    },
    [active]
  );

  const removeChat = useCallback(
    (chatId) => {
      setChats((prev) => prev.filter((c) => c.id !== chatId));
      if (active) roomClient.deleteAgentChat(chatId);
    },
    [active]
  );

  const clearAll = useCallback(() => {
    setChats([]);
    // chat_id rỗng = xoá toàn bộ lịch sử Agent của thành viên này.
    if (active) roomClient.deleteAgentChat(null);
  }, [active]);

  return { chats, loading, error, refresh, loadChat, saveTurn, removeChat, clearAll };
}
