// src/components/submission/ConfirmAction.jsx
// Dải xác nhận cho các thao tác XOÁ KHÔNG HOÀN TÁC ĐƯỢC trong khay nộp bài.
//
// Không dùng window.confirm: hộp thoại của trình duyệt khoá cả tab, không hiện
// được con số cụ thể sắp mất (bao nhiêu câu, bao nhiêu đáp án) theo đúng kiểu
// chữ của app, và ở chế độ phòng thì không nói được rằng cú bấm này xoá của CẢ
// NHÓM chứ không riêng máy đang bấm. Dải này nằm ngay dưới nút vừa bấm, nên đọc
// xong là thấy luôn mình đang xoá cái gì.
import { BTN_QUIET, BTN_DANGER } from "./tokens";
import { TrashIcon } from "../Icons";

/**
 * @param {string}   title    - câu hỏi, nêu rõ con số sắp mất
 * @param {string}   detail   - hệ quả (không hoàn tác, ảnh hưởng cả phòng…)
 * @param {string}   confirmLabel
 * @param {Function} onConfirm
 * @param {Function} onCancel
 */
function ConfirmAction({ title, detail, confirmLabel = "Xoá", onConfirm, onCancel }) {
  return (
    <div className="rounded-xl border border-red-300 bg-red-50 p-2.5">
      <p className="text-[11.5px] font-semibold leading-snug text-red-700">{title}</p>
      {detail && <p className="mt-0.5 text-[10.5px] leading-snug text-red-600/80">{detail}</p>}
      <div className="mt-2 flex justify-end gap-1.5">
        <button onClick={onCancel} className={BTN_QUIET}>Huỷ</button>
        <button onClick={onConfirm} className={BTN_DANGER}>
          <TrashIcon className="w-3 h-3" /> {confirmLabel}
        </button>
      </div>
    </div>
  );
}

export default ConfirmAction;
