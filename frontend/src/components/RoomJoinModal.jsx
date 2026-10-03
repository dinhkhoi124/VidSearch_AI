// src/components/RoomJoinModal.jsx
// Hỏi tên khi vào phòng. Không mật khẩu: phòng thi là LAN kín, tên chỉ để
// đồng đội biết frame nào của ai. Không bỏ qua được bằng Esc/bấm nền - chọn
// nhầm "làm một mình" giữa lúc thi thì cả nhóm mất đồng bộ mà không ai biết.
import { useState } from "react";
import { UsersIcon } from "./Icons";

function RoomJoinModal({ isOpen, onJoin, onSkip }) {
  const [name, setName] = useState("");
  if (!isOpen) return null;

  const submit = (e) => {
    e.preventDefault();
    const clean = name.trim();
    if (clean) onJoin(clean);
  };

  return (
    <div className="fixed inset-0 z-[95] flex items-center justify-center bg-slate-900/50 p-4">
      <form
        onSubmit={submit}
        className="bg-white rounded-xl shadow-2xl w-full max-w-sm text-slate-800 border border-slate-200 p-5"
      >
        <div className="flex items-center gap-2 font-semibold text-lg">
          <UsersIcon className="w-5 h-5 text-blue-600" /> Vào phòng nhóm
        </div>
        <p className="text-sm text-slate-500 mt-1.5">
          Cả nhóm dùng chung một giỏ đáp án và lịch sử truy vấn. Nhập tên để đồng đội
          biết frame nào là của bạn.
        </p>

        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={24}
          placeholder="Tên của bạn"
          className="mt-4 w-full px-3 py-2 bg-white border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500"
        />

        <div className="mt-4 flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={onSkip}
            className="text-sm text-slate-500 hover:text-slate-700 underline underline-offset-2"
          >
            Làm một mình
          </button>
          <button
            type="submit"
            disabled={!name.trim()}
            className="bg-blue-600 hover:bg-blue-700 disabled:bg-slate-300 text-white px-4 py-2 rounded-lg font-semibold text-sm transition-colors"
          >
            Vào phòng
          </button>
        </div>
      </form>
    </div>
  );
}

export default RoomJoinModal;
