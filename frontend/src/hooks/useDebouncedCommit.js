// src/hooks/useDebouncedCommit.js
// Hoãn việc ĐẨY ĐI, không hoãn việc HIỂN THỊ.
//
// Dùng cho những ô nhập mà mỗi lần đổi giá trị lại kéo theo một op nặng: ở đây
// là ô đáp án Q&A, nơi mỗi ký tự vốn bắn một POST /room/op, một lượt broadcast
// cả câu về mọi máy, và một lần JSON.stringify toàn bộ giỏ xuống localStorage.
// Component vẫn giữ giá trị của chính nó và vẽ lại tức thì; chỉ có lời gọi
// `commit` là gom lại thành một nhịp.
//
// flush() để bắn ngay lập tức - gọi khi rời ô, và tự động khi unmount (đổi câu
// giữa lúc đang gõ thì chữ vừa gõ vẫn phải về tới giỏ).
import { useCallback, useEffect, useRef } from "react";

export function useDebouncedCommit(commit, delay = 400) {
  const timer = useRef(null);
  // Có gì đang chờ hay chưa - KHÔNG suy ra từ `pending.current != null`, vì bản
  // thân chuỗi rỗng cũng là một giá trị hợp lệ cần gửi (xoá trắng đáp án).
  const has = useRef(false);
  const pending = useRef(null);
  // Giữ `commit` mới nhất trong ref: hàm này thường là arrow tạo lại mỗi render,
  // đưa vào deps thì mỗi phím gõ lại dựng một debounce mới và chẳng hoãn được gì.
  const commitRef = useRef(commit);
  commitRef.current = commit;

  const flush = useCallback(() => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    if (!has.current) return;
    has.current = false;
    const value = pending.current;
    pending.current = null;
    commitRef.current(value);
  }, []);

  const push = useCallback(
    (value) => {
      pending.current = value;
      has.current = true;
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        timer.current = null;
        flush();
      }, delay);
    },
    [delay, flush]
  );

  // Unmount = đổi câu, đóng khay, hoặc dòng bị xoá. Hai trường hợp đầu phải giữ
  // được chữ; trường hợp thứ ba thì op set_answer cho một id không còn trong giỏ
  // bị reducer bỏ qua, nên gửi thừa cũng vô hại.
  useEffect(() => flush, [flush]);

  return { push, flush };
}
