// src/components/submission/fields.jsx
// Ô nhập dùng chung trong khay nộp bài.
//
// Nhãn nằm TRONG khung: gọn hơn nhãn riêng một dòng, và cả khung sáng lên khi
// focus nên vẫn thấy rõ đang gõ ở đâu.
export function InlineField({ label, hint, children }) {
  return (
    <label
      title={hint}
      className="flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-2.5 transition-colors focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-500/20"
    >
      <span className="shrink-0 text-[10px] font-bold uppercase tracking-wider text-slate-400">{label}</span>
      {children}
    </label>
  );
}

export const INPUT =
  "w-full min-w-0 bg-transparent py-1.5 text-sm text-slate-800 focus:outline-none";
