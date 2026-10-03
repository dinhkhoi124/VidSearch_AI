// src/utils/memberStyle.js
// Cách hiển thị một thành viên trong phòng. Tách khỏi MemberBar.jsx vì
// SubmissionPanel và lịch sử nhóm cũng dùng, mà file chỉ-export-component thì
// React Fast Refresh mới chạy đúng.

const COLORS = [
  "bg-blue-500", "bg-emerald-500", "bg-amber-500",
  "bg-violet-500", "bg-rose-500", "bg-cyan-600", "bg-lime-600",
];

// Màu suy từ tên -> mỗi người một màu ổn định qua mọi máy, không cần lưu đâu cả.
export function memberColor(name) {
  let h = 0;
  for (let i = 0; i < (name || "").length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return COLORS[h % COLORS.length];
}

export function initials(name) {
  const parts = String(name || "?").trim().split(/\s+/);
  // Tên Việt: chữ cái đầu của TỪ CUỐI là cái người ta gọi nhau ("Minh" trong
  // "Nguyễn Văn Minh"), nên lấy nó làm chữ chính.
  const last = parts[parts.length - 1] || "?";
  return last.slice(0, 2).toUpperCase();
}
