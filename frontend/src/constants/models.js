// src/constants/models.js
//
// Model visual cho UI. Nguồn thật là BACKEND: GET /models đọc
// data/indexes/<model>.index trên đĩa của chính nó (xem hooks/useVisualModels.js
// + backend/routers/catalog.py). Danh sách cứng dưới đây chỉ là lưới an toàn
// cho lúc chưa gọi được backend.
//
// GIÁ TRỊ MODEL gửi cho backend là một chuỗi:
//   "siglip"                 -> search đơn trên index siglip
//   "siglip512+metaclip"     -> ensemble ad-hoc, trộn điểm chuẩn hoá theo max
//   "ensemble"               -> tổ hợp cấu hình sẵn trong .env (vẫn nhận, nhưng
//                               UI luôn quy về danh sách model tường minh để
//                               người dùng nhìn là biết đang trộn cái gì)
// Tổ hợp đi theo TỪNG REQUEST, không phải trạng thái chung của backend: cả nhóm
// dùng chung một backend, đổi cấu hình toàn cục giữa buổi thi là đổi kết quả
// của người khác mà họ không hề biết.

export const FALLBACK_SINGLES = [
  { value: "siglip", label: "siglip", dim: "" },
  { value: "clip", label: "clip", dim: "" },
];

export const DEFAULT_VISUAL_MODEL = "siglip";

/** GET /models -> các model ĐƠN chọn được (đã có index trên backend đó). */
export function toSingleOptions(data) {
  const usable = (data?.models || []).filter((m) => m.has_index);
  if (!usable.length) return FALLBACK_SINGLES;
  return usable.map((m) => ({
    value: m.value,
    // Số chiều tách riêng khỏi tên: siglip 1152d và metaclip 1024d nhìn tên
    // không phân biệt được, mà đó chính là thứ quyết định index nào khớp. Chip
    // chọn model xếp nó xuống dòng dưới cho tên đứng một mình, dễ quét mắt.
    dim: m.dim ? `${m.dim}d` : "",
    label: m.dim ? `${m.value} · ${m.dim}d` : m.value,
  }));
}

/** Các thành viên ensemble cấu hình trong .env của backend (đã lọc thiếu index). */
export function ensembleMembersOf(data) {
  return (data?.ensemble?.members || [])
    .filter((m) => m.has_index)
    .map((m) => m.model);
}

/** Model mặc định, dạng chuỗi đã chuẩn hoá ("siglip" hoặc "a+b"). */
export function pickDefaultModel(data) {
  const singles = toSingleOptions(data).map((m) => m.value);
  const members = ensembleMembersOf(data);
  // Backend đặt DEFAULT_MODEL=ensemble thì lấy đúng tổ hợp .env, tường minh.
  if (data?.default === "ensemble" && members.length) return members.join("+");
  if (singles.includes(data?.default)) return data.default;
  if (members.length) return members.join("+");
  return singles[0] || DEFAULT_VISUAL_MODEL;
}

/**
 * Chuẩn hoá giá trị model đã lưu (localStorage có thể còn của backend khác).
 * Bỏ model không còn index; rỗng thì rơi về mặc định.
 */
export function normalizeModel(stored, singles, members, fallback) {
  const known = new Set(singles);
  if (stored === "ensemble") {
    // Từ khoá cũ -> bung thành danh sách tường minh.
    return members.length ? members.join("+") : fallback;
  }
  const kept = String(stored || "")
    .split("+")
    .map((s) => s.trim())
    .filter((s) => known.has(s));
  if (!kept.length) return fallback;
  // Giữ THỨ TỰ theo danh sách của backend để nhãn không nhảy lung tung giữa
  // các lần bấm.
  return singles.filter((m) => kept.includes(m)).join("+");
}
