// src/components/HotkeysHelp.jsx
// Bảng phím tắt (mở bằng nút bàn phím trên header).
import { KeyboardIcon, CloseIcon } from "./Icons";

const ROWS = [
  ["1", "Chuyển sang tab Thủ công"],
  ["2", "Chuyển sang tab Agent"],
  ["s", "Mở giỏ đáp án của câu hiện tại / nộp bài"],
  ["Esc", "Đóng modal / bảng (đóng lớp trên cùng trước)"],
];

function HotkeysHelp({ isOpen, onClose }) {
  if (!isOpen) return null;
  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-900/40 p-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md text-slate-800 border border-slate-200" onClick={(e) => e.stopPropagation()}>
        <div className="bg-slate-50 border-b border-slate-200 p-3 rounded-t-xl flex justify-between items-center">
          <span className="inline-flex items-center gap-2 font-semibold"><KeyboardIcon className="w-5 h-5 text-slate-500" /> Phím tắt</span>
          <button onClick={onClose} className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100"><CloseIcon className="w-4 h-4" /></button>
        </div>
        <div className="p-4 space-y-2">
          {ROWS.map(([key, desc]) => (
            <div key={key} className="flex justify-between items-center gap-4 text-sm">
              <kbd className="bg-slate-100 border border-slate-300 rounded px-2 py-0.5 text-xs font-mono text-slate-600 whitespace-nowrap">{key}</kbd>
              <span className="text-slate-500 text-right flex-1">{desc}</span>
            </div>
          ))}

          <p className="pt-3 mt-1 border-t border-slate-200 text-xs text-slate-400">
            1 · 2 · s chỉ ăn khi con trỏ không nằm trong ô nhập và không có
            gallery nào đang mở.
          </p>
        </div>
      </div>
    </div>
  );
}

export default HotkeysHelp;
