// src/hooks/useRoom.js
// Vòng đời phòng thi nhóm: danh tính, kết nối, presence, lịch sử nhóm.
//
// Trả về một object truyền thẳng vào useAnswerBasket(room). Chưa chọn tên hoặc
// đã tắt chế độ phòng -> trả null, và giỏ chạy y hệt bản một người dùng.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import roomClient, {
  isRoomEnabled,
  readMember,
  saveMember,
  setRoomEnabled,
} from "../api/roomClient";

export function useRoom() {
  const [member, setMember] = useState(readMember);
  const [enabled, setEnabled] = useState(isRoomEnabled);
  const [status, setStatus] = useState(roomClient.getStatus);
  const [members, setMembers] = useState([]);
  const [history, setHistory] = useState([]);
  // Nhật ký lượt nộp của cả phòng (chỉ metadata - xem useSubmissionLog).
  const [submitLog, setSubmitLog] = useState([]);

  const active = enabled && !!member;

  useEffect(() => roomClient.subscribeStatus(setStatus), []);

  useEffect(() => {
    if (!active) return undefined;
    roomClient.start(member);
    return () => roomClient.stop();
  }, [active, member]);

  // Presence + lịch sử nhóm nghe ở đây; giỏ do useAnswerBasket nghe riêng.
  useEffect(() => {
    if (!active) return undefined;
    return roomClient.subscribe((msg) => {
      if (msg.type === "presence") setMembers(msg.members || []);
      else if (msg.type === "history_add") {
        setHistory((prev) => [msg.entry, ...prev.filter((e) => e.id !== msg.entry.id)].slice(0, 200));
      } else if (msg.type === "submitlog_add") {
        setSubmitLog((prev) => [msg.entry, ...prev.filter((e) => e.id !== msg.entry.id)].slice(0, 50));
      } else if (msg.type === "submitlog_clear") {
        setSubmitLog([]);
      } else if (msg.type === "snapshot") {
        setHistory(msg.state?.history || []);
        setSubmitLog(msg.state?.submitLog || []);
        if (msg.state?.members) setMembers(msg.state.members);
      }
    });
  }, [active]);

  const join = useCallback((name) => {
    setMember(saveMember(name));
    setRoomEnabled(true);
    setEnabled(true);
  }, []);

  /**
   * Đổi tên hiển thị, GIỮ NGUYÊN danh tính.
   *
   * saveMember tái sử dụng `id` cũ, nên với server đây vẫn là đúng một người:
   * presence gộp theo member_id (xem room_hub.presence) chứ không theo tên, nên
   * đổi tên KHÔNG đẻ ra một thành viên thứ hai trong thanh avatar.
   *
   * Không đụng tới `enabled` - khác `join`: đổi tên lúc đang làm một mình không
   * được lôi người ta vào phòng. Đổi `member` là đủ để effect ở trên ngắt rồi
   * nối lại socket, và tên mới đi kèm trong query của WS.
   */
  const rename = useCallback((name) => {
    const next = String(name || "").trim();
    if (!next) return;
    setMember((prev) => (prev && prev.name === next ? prev : saveMember(next)));
  }, []);

  // Bật lại phòng mà không hỏi tên nếu đã từng chọn; chưa có tên thì
  // `needsJoin` sẽ tự bật RoomJoinModal.
  const enable = useCallback(() => {
    setRoomEnabled(true);
    setEnabled(true);
  }, []);

  const leave = useCallback(() => {
    setRoomEnabled(false);
    setEnabled(false);
    setMembers([]);
  }, []);

  const pushGroupHistory = useCallback((mode, query, resultCount) => {
    roomClient.sendHistory({ mode, query, result_count: resultCount || 0 });
  }, []);

  // Đẩy một lượt tải zip lên phòng. Ngoài chế độ phòng thì im lặng bỏ qua -
  // useSubmissionLog vẫn ghi bản local như cũ.
  const sendSubmitLog = useCallback(
    (entry) => {
      if (!active) return;
      roomClient.sendSubmitLog(entry);
    },
    [active]
  );

  // Xoá nhật ký nộp của cả phòng (đi kèm "tạo đề mới" ở khay nộp bài): vòng mới
  // là gói mới nên bộ đếm 3 lượt phải về 0 trên mọi máy.
  const clearSubmitLog = useCallback(() => {
    setSubmitLog([]);
    if (!active) return;
    roomClient.clearSubmitLog();
  }, [active]);

  // Báo "đang mở câu mấy" - chỉ khi ĐỔI câu, tránh spam socket.
  const lastCurrent = useRef(null);
  const reportCurrent = useCallback((current) => {
    if (lastCurrent.current === current) return;
    lastCurrent.current = current;
    roomClient.sendCurrent(current);
  }, []);
  // Nối lại thì con trỏ câu ở server đã mất -> gửi lại.
  useEffect(() => {
    if (status.connected && lastCurrent.current != null) roomClient.sendCurrent(lastCurrent.current);
  }, [status.connected]);

  // Object cho useAnswerBasket. subscribe/sendOp là hàm của module (tham chiếu
  // cố định) nên object này chỉ đổi khi thật sự đổi phòng/danh tính.
  const basketRoom = useMemo(
    () => (active ? { member, sendOp: roomClient.sendOp, subscribe: roomClient.subscribe } : null),
    [active, member]
  );

  return {
    member,
    enabled,
    active,
    needsJoin: enabled && !member,
    status,
    members,
    history,
    submitLog,
    join,
    rename,
    enable,
    leave,
    pushGroupHistory,
    sendSubmitLog,
    clearSubmitLog,
    reportCurrent,
    basketRoom,
  };
}
