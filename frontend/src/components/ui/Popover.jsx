// src/components/ui/Popover.jsx
// Popover đóng khi bấm ra ngoài, dùng chung cho các menu nhỏ trong app.
//
// Wrapper bọc CẢ nút mở lẫn tấm popover - không phải chỉ tấm popover. Nếu chỉ
// bọc tấm popover thì cú bấm vào chính nút mở vừa bị tính là "bấm ra ngoài"
// (đóng), vừa chạy onClick của nút (mở lại) -> popover không bao giờ đóng được
// bằng nút của nó.
//
// Esc do phím tắt toàn cục xử lý (xem closeTopOverlay ở SearchPage).
import { useEffect, useRef } from "react";

/**
 * @param {boolean}  open
 * @param {Function} onClose
 * @param {ReactNode} panel      - nội dung tấm popover
 * @param {string}   panelClass  - class định vị + kích thước tấm popover
 * @param {string}   className   - class cho wrapper (mặc định `relative`)
 * @param {ReactNode} children   - nút mở (và bất cứ thứ gì đi cùng nó)
 */
function Popover({ open, onClose, panel, panelClass = "", className = "", children }) {
  const wrapRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) onClose();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open, onClose]);

  return (
    <div ref={wrapRef} className={className || "relative"}>
      {children}
      {open && (
        <div
          className={`absolute z-50 rounded-xl border border-slate-200 bg-white shadow-2xl ${panelClass}`}
        >
          {panel}
        </div>
      )}
    </div>
  );
}

export default Popover;
