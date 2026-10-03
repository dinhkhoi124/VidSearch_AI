// src/components/submission/tokens.js
// Ngôn ngữ hình ảnh DÙNG CHUNG của khay nộp bài.
//
// Trước đây mỗi file tự chế class riêng, nên cùng một thứ (nút icon, nhãn nhỏ,
// dòng menu) mỗi chỗ một kích thước, và khay có tới bốn màu nhấn cạnh nhau.
// Gom vào đây thì "đồng nhất" là mặc định chứ không phải việc phải nhớ.
//
// Quy ước MÀU - mỗi màu đúng một nghĩa, không dùng để trang trí:
//   blue    = nhấn / đang chọn / hành động chính
//   emerald = đã có đáp án, đã xong
//   violet  = ứng viên TRAKE (một dòng CSV)
//   amber   = cảnh báo không chặn
//   red     = lỗi chặn nộp / thao tác xoá
//   slate   = mọi thứ còn lại
//
// Quy ước CỠ CHỮ - chỉ bốn bậc:
//   14.5px tiêu đề khay · 11.5px nội dung · 10.5px phụ chú · 10px nhãn hoa
//
// Viết ĐỦ tên class (không ghép chuỗi lúc chạy): Tailwind quét mã nguồn theo
// văn bản, class dựng động sẽ không có trong bundle.

// Lề ngang chuẩn của khay - mọi hàng phải thẳng một mép.
export const PAD_X = "px-3";

// Nhãn hoa nhỏ đứng đầu một khối ("ĐỀ CÂU 1", "BỘ ĐỀ").
export const LABEL = "text-[10px] font-bold uppercase tracking-wider text-slate-400";

// Dòng phụ chú: tên file sắp nộp, hạn mức, số đếm.
export const META = "text-[10.5px] text-slate-400 tabular-nums";

// Khối nội dung nổi trên nền khay (thẻ đáp án, khối đề bài).
export const CARD = "rounded-xl border border-slate-200 bg-white";

// Nút chỉ có icon ở hàng tiêu đề (⚙, ✕).
export const ICON_BTN =
  "flex h-7 w-7 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700";

// Nút chữ tí hon nằm nép trong một hàng ("Sửa", "Chép").
export const MINI_BTN =
  "inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-[10.5px] font-semibold transition-colors";

// Một dòng trong popover ⚙.
export const MENU_ROW =
  "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-[11.5px] transition-colors";

// Cặp nút của dải xác nhận / hộp thoại nhỏ.
export const BTN_QUIET =
  "rounded-lg border border-slate-300 bg-white px-2.5 py-1 text-[11px] font-semibold text-slate-600 transition-colors hover:bg-slate-50";
export const BTN_DANGER =
  "inline-flex items-center gap-1 rounded-lg bg-red-600 px-2.5 py-1 text-[11px] font-semibold text-white transition-colors hover:bg-red-700";
