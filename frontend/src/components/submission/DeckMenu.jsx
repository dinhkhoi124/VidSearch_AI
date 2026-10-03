// src/components/submission/DeckMenu.jsx
// Nội dung popover ⚙ - phạm vi CẢ BỘ ĐỀ.
//
// Ranh giới với popover "Sửa" ở dải cấu hình: mọi thứ trong này tác động lên
// TOÀN BỘ đề (số câu, gói đề, xoá sạch); "Sửa" chỉ đụng tới câu đang mở (Query
// ID, Max, số event). Trước đây hai nút mở chung một popover trộn lẫn hai phạm
// vi, nên bấm "Sửa" một câu vẫn thấy nút đổi số câu của cả đề ngay bên cạnh.
import { useState } from "react";
import { NumQuestionsField } from "../QuestionSwitcher";
import ConfirmAction from "./ConfirmAction";
import { LABEL, META, MENU_ROW } from "./tokens";
import { UploadIcon, TrashIcon, RefreshIcon } from "../Icons";

function DeckMenu({ basket, answeredCount, attempts, roomActive, onReopenSetup, onResetDeck, onClose }) {
  const { numQuestions, totalCount } = basket;
  // "cần xác nhận cái gì" thay vì hai cờ boolean rời: hai dải xác nhận không bao
  // giờ được hiện cùng lúc, mà bấm cái này rồi bấm cái kia phải đổi hẳn câu hỏi.
  const [confirming, setConfirming] = useState(null); // null | "answers" | "deck"

  const run = (fn) => { fn(); setConfirming(null); onClose(); };

  return (
    <div className="space-y-2">
      <div className={LABEL}>Bộ đề</div>

      <label className="flex items-center justify-between gap-2 text-[11.5px] text-slate-600">
        Số câu của đề
        <NumQuestionsField value={numQuestions} onCommit={basket.setNumQuestions} />
      </label>

      <p className={`${META} leading-snug`}>
        {numQuestions} câu · {answeredCount} câu có đáp án · {totalCount} đáp án
        <br />
        Đã tải {attempts} lượt nộp {roomActive ? "(cả phòng)" : "(máy này)"}
      </p>

      <div className="space-y-1 border-t border-slate-100 pt-2">
        <button
          onClick={() => { onClose(); onReopenSetup(); }}
          title="Thả gói .zip hoặc các file query-*.txt của BTC"
          className={`${MENU_ROW} text-slate-600 hover:bg-slate-100`}
        >
          <UploadIcon className="w-3.5 h-3.5 shrink-0" /> Nhập / bổ sung gói đề
        </button>

        {totalCount > 0 && confirming !== "answers" && (
          <button
            onClick={() => setConfirming("answers")}
            title="Giữ nguyên đề (số câu, task, Query ID, đề bài), chỉ xoá các frame đã chọn"
            className={`${MENU_ROW} text-slate-600 hover:bg-red-50 hover:text-red-600`}
          >
            <TrashIcon className="w-3.5 h-3.5 shrink-0" /> Xoá đáp án của tất cả {numQuestions} câu
          </button>
        )}
        {confirming === "answers" && (
          <ConfirmAction
            title={`Xoá ${totalCount} đáp án của tất cả các câu?`}
            detail={
              "Đề vẫn còn nguyên (số câu, loại task, Query ID, đề bài). " +
              "Không hoàn tác được, và cả phòng cùng bị xoá."
            }
            confirmLabel={`Xoá ${totalCount} đáp án`}
            onCancel={() => setConfirming(null)}
            onConfirm={() => run(basket.clearAll)}
          />
        )}
      </div>

      <div className="space-y-1 border-t border-slate-100 pt-2">
        {confirming !== "deck" ? (
          <button
            onClick={() => setConfirming("deck")}
            title="Sang vòng thi mới: xoá sạch đề hiện tại rồi nhập gói đề khác"
            className={`${MENU_ROW} font-semibold text-red-600 hover:bg-red-50`}
          >
            <RefreshIcon className="w-3.5 h-3.5 shrink-0" /> Tạo đề mới - xoá sạch tất cả
          </button>
        ) : (
          <ConfirmAction
            title={
              `Xoá toàn bộ ${numQuestions} câu` +
              (totalCount ? `, ${totalCount} đáp án` : ", chưa có đáp án nào") +
              (attempts ? ` và nhật ký ${attempts} lượt nộp?` : "?")
            }
            detail={
              "Xoá cả đề bài, loại task và Query ID; bộ đếm lượt nộp về 0. " +
              "Không hoàn tác được" +
              (roomActive ? ", và cả phòng cùng bị xoá chứ không riêng máy này." : ".")
            }
            confirmLabel="Xoá hết & tạo đề mới"
            onCancel={() => setConfirming(null)}
            onConfirm={() => run(onResetDeck)}
          />
        )}
      </div>
    </div>
  );
}

export default DeckMenu;
