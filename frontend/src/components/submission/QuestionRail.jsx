// src/components/submission/QuestionRail.jsx
// Dải câu hỏi dựng ĐỨNG bên trái khay nộp bài.
//
// Thay cho lưới 5 cột cũ: lưới ăn ~200px chiều cao của khay, trong khi thứ dùng
// liên tục (danh sách đáp án) chỉ còn một ô bé xíu. Xếp dọc thì mỗi câu là một
// dòng ~30px, thấy được ~18 câu cùng lúc mà KHÔNG tốn chiều cao nào của danh
// sách - vì rail nằm ở trục ngang.
//
// Trạng thái đọc được ngay không cần chú thích màu riêng:
//   - vạch dọc xanh dương + nền blue-50 = câu đang làm;
//   - số đếm xanh lá                    = đã có đáp án;
//   - dấu chấm xám                      = chưa có.
import { useEffect, useRef } from "react";
import { TASK_SHORT } from "../../utils/submissionFormat";
import { META } from "./tokens";

// Ba tone -> ba bộ class. Gom sẵn thay vì nối chuỗi trong JSX để mỗi trạng thái
// đọc được thành một khối.
const TONE = {
  active: {
    row: "bg-blue-50",
    bar: "bg-blue-600",
    qid: "text-blue-700",
    tag: "text-blue-500",
    count: "text-blue-600",
  },
  filled: {
    row: "hover:bg-slate-50",
    bar: "bg-transparent",
    qid: "text-slate-600",
    tag: "text-slate-400",
    count: "text-emerald-600",
  },
  empty: {
    row: "hover:bg-slate-50",
    bar: "bg-transparent",
    qid: "text-slate-400",
    tag: "text-slate-300",
    count: "text-slate-300",
  },
};

function RailRow({ qid, count, taskType, queryText, active, onPick, rowRef }) {
  const tag = TASK_SHORT[taskType] || taskType;
  const t = active ? TONE.active : count > 0 ? TONE.filled : TONE.empty;
  // Rail chỉ đủ chỗ cho số và nhãn task, nhưng thứ để CHỌN câu tiếp theo lại là
  // đề bài -> đưa đề vào tooltip, xem lướt cả đề không phải bấm qua từng câu.
  const title =
    `Câu ${qid} · ${tag} · ${count ? `${count} đáp án` : "chưa có đáp án"}` +
    (queryText ? `\n\n${queryText}` : "");

  return (
    <button
      ref={rowRef}
      onClick={() => onPick(qid)}
      aria-current={active ? "true" : undefined}
      title={title}
      className={`relative flex h-[26px] w-full items-center gap-1.5 rounded-lg pl-2.5 pr-1.5 transition-colors ${t.row}`}
    >
      <span className={`absolute inset-y-1 left-0.5 w-0.5 rounded-full ${t.bar}`} />
      <span className={`w-[17px] shrink-0 text-left text-[11.5px] font-semibold tabular-nums ${t.qid}`}>
        {qid}
      </span>
      {/* "TRAKE" là nhãn dài nhất - rail phải đủ rộng cho nó, vì cắt thành
          "TR…" thì không phân biệt được với "TRAKE" của câu khác. */}
      <span className={`min-w-0 flex-1 truncate text-left text-[8px] font-bold uppercase tracking-wide ${t.tag}`}>
        {tag}
      </span>
      <span className={`shrink-0 text-[10.5px] font-bold tabular-nums ${t.count}`}>
        {count || "·"}
      </span>
    </button>
  );
}

// `onOpenDeck`: mở popover ⚙ (cấu hình CẢ BỘ ĐỀ) - "số câu" và "câu bị ẩn" đều
// là chuyện của cả đề chứ không của riêng câu nào.
function QuestionRail({ basket, onOpenDeck }) {
  const { questionList, current, numQuestions, hiddenWithData } = basket;
  const answered = questionList.filter((q) => q.count > 0).length;
  const pct = Math.round((answered / Math.max(1, numQuestions)) * 100);

  // Cú nhảy từ một dòng lỗi trong khay nộp bài phải kéo rail theo, nếu không
  // thì câu đang làm nằm ngoài tầm nhìn.
  const activeRef = useRef(null);
  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: "nearest" });
  }, [current]);

  return (
    <div className="flex w-[94px] shrink-0 flex-col border-r border-slate-200 bg-white">
      {/* Cao đúng bằng hàng tiêu đề bên phải (pt-2.5 + nội dung + pb-1.5) để hai
          cột bắt đầu trên cùng một đường ngang. */}
      <div className="border-b border-slate-200 px-2.5 pb-2 pt-2.5">
        <div className={META} title={`${answered}/${numQuestions} câu đã có đáp án`}>
          <span className="font-bold text-slate-700">{answered}</span>/{numQuestions} câu
        </div>
        <div className="mt-1.5 h-[3px] overflow-hidden rounded-full bg-slate-100">
          <div
            className="h-full rounded-full bg-emerald-500 transition-all duration-300"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      <div className="flex-1 space-y-px overflow-y-auto p-1.5">
        {questionList.map((q) => (
          <RailRow
            key={q.qid}
            {...q}
            active={q.qid === current}
            onPick={basket.setCurrent}
            rowRef={q.qid === current ? activeRef : null}
          />
        ))}
      </div>

      <div className="space-y-1 border-t border-slate-200 p-1.5">
        {hiddenWithData.length > 0 && (
          <button
            onClick={onOpenDeck}
            title={`Câu ${hiddenWithData.join(", ")} còn đáp án nhưng đang bị ẩn (ngoài ${numQuestions} câu) - tăng “Số câu” để xem lại`}
            className="w-full rounded-lg bg-amber-50 py-1 text-center text-[10px] font-semibold text-amber-700 transition-colors hover:bg-amber-100"
          >
            {hiddenWithData.length} câu bị ẩn
          </button>
        )}
        <button
          onClick={onOpenDeck}
          title="Cấu hình cả bộ đề: số câu, nhập gói đề, tạo đề mới"
          className="w-full rounded-lg py-1 text-center text-[10px] font-semibold text-slate-400 transition-colors hover:bg-slate-50 hover:text-slate-700"
        >
          {numQuestions} câu
        </button>
      </div>
    </div>
  );
}

export default QuestionRail;
