// src/components/QuestionSwitcher.jsx
// Pill nổi góc dưới-phải: cho biết ĐANG TÌM ĐÁP ÁN CHO CÂU NÀO và có bao nhiêu
// frame đã bỏ vào giỏ của câu đó. Mũi tên = câu trước/sau, bấm vào số = mở bảng
// chọn nhanh 1..N.
import { useEffect, useState } from "react";
import { ChevronLeftIcon, ChevronRightIcon, InboxIcon } from "./Icons";
import { TASK_SHORT } from "../utils/submissionFormat";
import Popover from "./ui/Popover";

/**
 * Ô nhập "số câu của đề". Chỉ áp dụng khi rời ô/Enter: nếu ghi trực tiếp theo
 * từng ký tự, xoá ô để gõ lại sẽ tụt N về 1 và kéo câu đang làm về câu 1.
 *
 * Export vì khay nộp bài cũng dùng (trong popover ⚙ và màn hình thiết lập).
 */
export function NumQuestionsField({ value, onCommit, className = "" }) {
  const [draft, setDraft] = useState(String(value));

  useEffect(() => setDraft(String(value)), [value]);

  const commit = () => {
    const n = Math.round(Number(draft));
    if (Number.isFinite(n) && n >= 1) onCommit(n);
    else setDraft(String(value));
  };

  return (
    <input
      type="number"
      min="1"
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commit(); e.currentTarget.blur(); } }}
      title="Số câu của đề - nhấn Enter hoặc bấm ra ngoài để áp dụng"
      className={`w-14 px-2 py-1 bg-white border border-slate-300 rounded-md text-xs font-semibold text-slate-700 tabular-nums text-center focus:outline-none focus:ring-2 focus:ring-blue-500/30 ${className}`}
    />
  );
}

// Một ô số trong lưới. Ba thông tin đọc được ngay không cần hover:
//   - nền/viền  = đã có đáp án (xanh lá nhạt) hay chưa (trắng);
//   - viền xanh dương + quầng = câu đang làm;
//   - số nhỏ góc trên phải = có mấy đáp án; nhãn dưới = loại task - MỌI câu đều
//     hiện nhãn (kể cả KIS) để các ô cao bằng nhau và số câu không bị lệch dòng;
//     KIS tô nhạt hơn vì là mặc định, QA/TRAKE đậm hơn cho dễ soi trước khi nộp.
// Dùng viền + ring-bên-trong thay cho `outline-offset`: outline nằm NGOÀI ô nên bị
// khung cuộn của lưới cắt mất cạnh trên/dưới (chỉ còn 2 vạch hai bên).
//
// Số + nhãn xếp bằng flex-col căn giữa (KHÔNG absolute) để cụm chữ luôn nằm giữa
// ô như nhau ở mọi trạng thái; chỉ badge đếm mới định vị tuyệt đối ở góc.
// Nhãn task lấy đúng màu chữ của ô rồi giảm opacity - nhờ vậy ô xanh lá / xanh
// dương / trắng vẫn hài hoà mà không cần bảng màu riêng cho nhãn.
function QuestionCell({ qid, count, taskType, active, onPick }) {
  const filled = count > 0;
  const tag = TASK_SHORT[taskType] || taskType;
  const isDefaultTask = taskType === "kis";

  const tone = active
    ? "border-blue-500 bg-blue-50 text-blue-700 inset-ring-1 inset-ring-blue-500"
    : filled
      ? "border-emerald-200 bg-emerald-50 text-emerald-700 hover:border-emerald-300 hover:bg-emerald-100"
      : "border-slate-200 bg-white text-slate-500 hover:border-slate-300 hover:bg-slate-50 hover:text-slate-700";

  return (
    <button
      onClick={() => onPick(qid)}
      aria-current={active ? "true" : undefined}
      title={`Câu ${qid} · ${tag} · ${count ? `${count} đáp án` : "chưa có đáp án"}`}
      className={`relative flex h-14 flex-col items-center justify-center gap-1 rounded-xl border px-1 transition-colors ${tone}`}
    >
      <span className="text-base font-semibold leading-none tabular-nums">{qid}</span>
      <span
        className={`max-w-full truncate text-[9px] font-bold uppercase leading-none tracking-wider ${
          isDefaultTask ? "opacity-40" : "opacity-70"
        }`}
      >
        {tag}
      </span>
      {filled && (
        <span
          className={`absolute top-1 right-1.5 text-[10px] font-bold leading-none tabular-nums ${
            active ? "text-blue-600" : "text-emerald-600"
          }`}
        >
          {count}
        </span>
      )}
    </button>
  );
}

// Một mục trong hàng chú thích: ô mẫu đúng như trong lưới + nhãn.
function LegendItem({ swatch, children }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`w-3 h-3 rounded-[3px] border ${swatch}`} />
      {children}
    </span>
  );
}

/**
 * Khối chọn câu dùng chung cho popover (pill) và panel nộp bài: tiến độ + lưới số.
 * `legend`: "full" (popover, có chỗ) | "mini" (panel, tiết kiệm chiều cao) | "none".
 */
export function QuestionPicker({ basket, cols = 6, maxHeight = "max-h-40", legend = "full" }) {
  const { questionList, current, numQuestions, hiddenWithData } = basket;
  const answered = questionList.filter((q) => q.count > 0).length;
  const pct = Math.round((answered / Math.max(1, numQuestions)) * 100);

  return (
    <div>
      {/* Một hàng duy nhất: nhãn - tiến độ (số + thanh) - ô nhập số câu. Gộp thanh
          tiến độ vào cùng hàng để tiết kiệm một dòng trong drawer. */}
      <div className="flex items-center gap-2.5">
        <span className="text-[13px] font-semibold text-slate-700 shrink-0">Câu hỏi</span>
        <span
          className="px-1.5 py-0.5 rounded-md bg-slate-100 text-[11px] font-semibold text-slate-600 tabular-nums shrink-0"
          title={`${answered}/${numQuestions} câu đã có đáp án`}
        >
          {answered}/{numQuestions}
        </span>
        <div className="flex-1 h-1.5 rounded-full bg-slate-100 overflow-hidden min-w-8">
          <div
            className="h-full bg-emerald-500 rounded-full transition-all duration-300"
            style={{ width: `${pct}%` }}
          />
        </div>
        <label className="flex items-center gap-1.5 text-[11px] text-slate-400 shrink-0">
          Số câu
          <NumQuestionsField value={numQuestions} onCommit={basket.setNumQuestions} />
        </label>
      </div>

      {/* p-0.5 để quầng/viền ô đang chọn không bị khung cuộn cắt mất */}
      <div className={`${maxHeight} overflow-y-auto mt-2.5 -mx-0.5 p-0.5`}>
        <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
          {questionList.map((q) => (
            <QuestionCell key={q.qid} {...q} active={q.qid === current} onPick={basket.setCurrent} />
          ))}
        </div>
      </div>

      {legend !== "none" && (
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10.5px] text-slate-400">
          <LegendItem swatch="bg-emerald-50 border-emerald-300">đã có{legend === "full" ? " đáp án" : ""}</LegendItem>
          <LegendItem swatch="bg-white border-slate-200">chưa có</LegendItem>
          <LegendItem swatch="bg-blue-50 border-blue-500">đang làm</LegendItem>
          {legend === "full" && (
            <>
              <span className="text-slate-300">·</span>
              <span>số nhỏ = số đáp án</span>
            </>
          )}
        </div>
      )}

      {hiddenWithData.length > 0 && (
        <p className="mt-1.5 text-[11px] text-amber-600">
          Câu {hiddenWithData.join(", ")} còn đáp án nhưng đang bị ẩn (ngoài {numQuestions} câu) - tăng “Số câu” để xem lại.
        </p>
      )}
    </div>
  );
}

/**
 * Chỉ báo TRAKE: cho biết frame thêm tiếp theo sẽ điền vào EVENT nào của ứng
 * viên nào. Items của câu TRAKE được cắt tuần tự theo numEvents, nên vị trí kế
 * tiếp suy được thẳng từ số lượng - không cần thêm state.
 *
 * `flat`: bản dùng trong khay nộp bài - pill nổi bị ẩn khi khay mở nên chỉ báo
 * phải chuyển vào trong đó, mà ở đó nó nằm sẵn trên một dải trắng có viền rồi
 * nên không cần khung + bóng riêng nữa.
 */
export function TrakeProgress({ count, numEvents, flat = false }) {
  const cand = Math.floor(count / numEvents) + 1;
  const nextEvent = (count % numEvents) + 1;

  return (
    <div
      title={`Câu TRAKE ${numEvents} event - frame thêm tiếp theo sẽ vào event ${nextEvent} của đáp án #${cand}`}
      className={
        flat
          ? "flex items-center gap-2"
          : "mb-2 flex items-center gap-2 rounded-lg border border-violet-200 bg-white px-2.5 py-1.5 shadow-lg"
      }
    >
      <span className="text-[10px] font-bold uppercase tracking-wider text-violet-500">
        Đáp án #{cand}
      </span>
      <div className="flex gap-1">
        {Array.from({ length: numEvents }, (_, i) => (
          <span
            key={i}
            className={`flex h-5 w-5 items-center justify-center rounded text-[10px] font-bold tabular-nums ${
              i + 1 < nextEvent
                ? "bg-violet-500 text-white"
                : i + 1 === nextEvent
                  ? "bg-white text-violet-600 ring-2 ring-violet-500"
                  : "bg-slate-100 text-slate-400"
            }`}
          >
            {i + 1}
          </span>
        ))}
      </div>
      {flat && (
        <span className="ml-auto whitespace-nowrap text-[10.5px] text-slate-400">
          <kbd className="rounded border border-slate-300 bg-slate-100 px-1 text-[9.5px] font-bold text-slate-600">a</kbd>{" "}
          điền vào event {nextEvent}
        </span>
      )}
    </div>
  );
}

function QuestionSwitcher({ basket, isOpen, onToggle, onClose, onOpenBasket }) {
  const { current, numQuestions, count, totalCount, taskType, numEvents } = basket;
  const arrow =
    "w-8 h-9 flex items-center justify-center text-slate-500 hover:text-blue-600 hover:bg-slate-100 disabled:opacity-30 disabled:hover:bg-transparent transition-colors";
  // Badge đếm đáp án: viền trắng để tách khỏi nền xanh của nút tròn.
  const badge =
    "pointer-events-none absolute -top-1 -right-1 z-10 flex h-5 min-w-5 items-center justify-center rounded-full bg-emerald-500 px-1 text-[11px] font-bold text-white tabular-nums ring-2 ring-white shadow-sm";

  return (
    <Popover
      open={isOpen}
      onClose={onClose}
      className="fixed z-50 bottom-5 right-5"
      panelClass="qs-anim-pop bottom-full right-0 mb-2 w-80 max-w-[calc(100vw-2.5rem)] p-3"
      panel={
        <>
          <QuestionPicker basket={basket} cols={5} maxHeight="max-h-64" />

          <div className="mt-2.5 flex items-center justify-between border-t border-slate-200 pt-2">
            <span className="text-[11px] text-slate-400 tabular-nums">
              Tổng {totalCount} đáp án / {numQuestions} câu
            </span>
            <button
              onClick={onOpenBasket}
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-blue-600 hover:bg-blue-50 px-2 py-1 rounded"
              title="Mở giỏ đáp án của câu này (phím s)"
            >
              <InboxIcon className="w-3.5 h-3.5" /> Mở giỏ câu {current}
            </button>
          </div>
        </>
      }
    >
      {taskType === "trake" && numEvents > 0 && (
        <TrakeProgress count={count} numEvents={numEvents} />
      )}

      {/* Thu gọn = nút tròn chỉ hiện số câu đang làm (ít che màn hình khi lướt
          kết quả); mở ra mới bung thành pill đầy đủ có mũi tên trước/sau. Badge
          đếm đáp án giữ nguyên ở cả hai trạng thái để không mất tín hiệu. */}
      {isOpen ? (
        // KHÔNG overflow-hidden: badge đếm nhô ra ngoài viền pill sẽ bị cắt mất.
        <div className="qs-anim-pill flex items-center bg-white border border-slate-200 rounded-full shadow-lg shadow-slate-900/10 ring-1 ring-slate-900/5">
          <button onClick={basket.prev} disabled={current <= 1} className={`${arrow} pl-1 rounded-l-full`} title="Câu trước">
            <ChevronLeftIcon className="w-4 h-4" />
          </button>
          <button
            onClick={onToggle}
            title="Đang tìm đáp án cho câu này - bấm để thu gọn"
            className="relative px-2.5 h-9 font-semibold text-sm text-slate-800 hover:bg-slate-50 transition-colors whitespace-nowrap"
          >
            Câu <span className="text-blue-600 tabular-nums">{current}</span>
            <span className="text-slate-400 font-normal tabular-nums">/{numQuestions}</span>
            {count > 0 && (
              <span className={badge}>{count}</span>
            )}
          </button>
          <button onClick={basket.next} disabled={current >= numQuestions} className={`${arrow} pr-1 rounded-r-full`} title="Câu sau">
            <ChevronRightIcon className="w-4 h-4" />
          </button>
        </div>
      ) : (
        // Vòng ngoài chỉ để chứa badge + hiệu ứng nở; `group` cho phép nút trong
        // phản ứng cả khi trỏ vào badge (badge nằm ngoài rìa nút).
        <div className="qs-anim-pop group relative">
          <button
            onClick={onToggle}
            aria-label={`Câu ${current} trên ${numQuestions} - chọn câu khác`}
            title={`Đang tìm đáp án cho câu ${current}/${numQuestions} - bấm để chọn câu khác`}
            className="flex h-12 w-12 items-center justify-center rounded-full bg-blue-600 text-[17px] font-bold text-white tabular-nums shadow-lg shadow-slate-900/15 transition-[transform,background-color] duration-200 ease-out group-hover:scale-105 group-hover:bg-blue-700 active:scale-95 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-500/40"
          >
            {current}
          </button>
          {count > 0 && <span className={badge}>{count}</span>}
        </div>
      )}
    </Popover>
  );
}

export default QuestionSwitcher;
