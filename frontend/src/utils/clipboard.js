// src/utils/clipboard.js
// Chép text vào clipboard, chạy được cả ngoài secure context.
//
// navigator.clipboard CHỈ tồn tại ở https hoặc localhost. Lúc thi, đồng đội mở
// app bằng http://192.168.x.x của máy chủ - đúng cái trường hợp API kia không
// có - nên phải còn đường lui bằng execCommand, dù nó đã deprecated.
export async function copyText(text) {
  const value = String(text ?? "");
  if (!value) return false;

  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch {
    // Bị từ chối quyền / không phải secure context -> thử cách cũ bên dưới.
  }

  try {
    const ta = document.createElement("textarea");
    ta.value = value;
    // Phải nằm trong DOM và select được thì execCommand mới chép; đẩy ra ngoài
    // màn hình và readOnly để không nháy con trỏ hay bật bàn phím ảo.
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "-1000px";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}
