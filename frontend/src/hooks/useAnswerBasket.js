// src/hooks/useAnswerBasket.js
// GIỎ ĐÁP ÁN THEO TỪNG CÂU của đề (câu 1..N).
// Mỗi câu giữ:
//   - items: danh sách frame CÓ THỨ TỰ (rank = vị trí, bắt đầu từ 1) để nộp;
//   - taskType/queryId/maxRows: cấu hình nộp riêng, vì một đề có thể trộn
//     KIS / Q&A / TRAKE.
// `current` = câu đang tìm đáp án; mọi thao tác thêm/bỏ mặc định rơi vào câu này.
//
// PHÒNG THI NHÓM: khi truyền `room` (xem hooks/useRoom.js), giỏ trở thành của
// CẢ NHÓM - server là nguồn sự thật, hook này chỉ:
//   1. áp dụng op tại chỗ ngay để UI không khựng chờ mạng,
//   2. gửi op lên server,
//   3. nhận state server phát về và ghi đè.
// localStorage vẫn được ghi trong MỌI trường hợp: đó là bản sao bền vững để
// backend chết vẫn làm việc tiếp được. Không truyền `room` -> hook chạy y hệt
// bản một người dùng.
//
// Logic thuần nằm ở hooks/basketReducer.js (dùng chung với backend).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  MAX_QUESTIONS,
  applyOp,
  applyOps,
  clampQ,
  defaultQuestion,
  normalize,
  toEntry,
} from "./basketReducer";
import { MAX_ROWS, defaultQueryId } from "../utils/submissionFormat";
import { usePersistedState } from "./usePersistedState";

const KEY = "aic.basket.v2";
// Key của phiên bản cũ (một giỏ phẳng, không có câu) - dùng để di trú, KHÔNG xoá
// để còn rollback được nếu cần.
const LEGACY_KEY = "aic.basket";
const LEGACY_TASK = "aic.tasktype";
const LEGACY_QUERY_ID = "aic.queryid";
const LEGACY_MAX_ROWS = "aic.maxrows";

export { MAX_QUESTIONS, defaultQuestion };

function readJSON(key) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

// Di trú giỏ phẳng cũ -> câu 1 (giữ luôn cấu hình nộp toàn cục cũ).
function migrateLegacy() {
  const items = readJSON(LEGACY_KEY);
  if (!Array.isArray(items) || items.length === 0) return null;
  const q1 = defaultQuestion(1);
  q1.items = items.filter((it) => it && it.id != null);
  const taskType = readJSON(LEGACY_TASK);
  const queryId = readJSON(LEGACY_QUERY_ID);
  const maxRows = readJSON(LEGACY_MAX_ROWS);
  if (typeof taskType === "string") q1.taskType = taskType;
  if (typeof queryId === "string" && queryId.trim()) q1.queryId = queryId;
  if (Number(maxRows) > 0) q1.maxRows = Number(maxRows);
  return { numQuestions: 1, questions: { 1: q1 } };
}

function load() {
  const stored = readJSON(KEY);
  if (stored) return normalize(stored);
  const migrated = migrateLegacy();
  return migrated ? normalize(migrated) : { numQuestions: 1, questions: {} };
}

export function useAnswerBasket(room) {
  const [state, setState] = useState(load);
  // Câu đang làm là chuyện RIÊNG của từng máy: 5 người chia nhau mỗi người vài
  // câu, đồng bộ con trỏ này sẽ giật câu của nhau.
  const [current, setCurrentRaw] = usePersistedState("aic.current", 1);

  // Giữ `room` trong ref để các callback bên dưới không phải phụ thuộc vào nó
  // (room đổi mỗi lần đổi trạng thái kết nối; callback đổi theo sẽ khiến toàn
  // bộ lưới kết quả re-render - lưới có thể tới hàng nghìn ô).
  const roomRef = useRef(room);
  roomRef.current = room;

  // Ghi localStorage = JSON.stringify CẢ BỘ ĐỀ (tới 200 câu × 100 dòng), chạy
  // đồng bộ trên main thread. Trước đây nó nổ theo từng ký tự gõ vào ô đáp án,
  // mà là HAI lần mỗi ký tự: một cho op của mình, một cho echo server phát về.
  // Hoãn nửa giây để gom lại thì được, nhưng MẤT thì không: bản localStorage là
  // phao cứu sinh để backend chết vẫn làm việc tiếp (xem chú thích đầu file),
  // nên tab ẩn đi là phải ghi ngay lập tức, không chờ hết nhịp hoãn.
  const stateRef = useRef(state);
  stateRef.current = state;

  const persist = useCallback(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(stateRef.current));
    } catch {
      // bỏ qua nếu localStorage đầy/bị chặn
    }
  }, []);

  useEffect(() => {
    const t = setTimeout(persist, 500);
    return () => clearTimeout(t);
  }, [state, persist]);

  useEffect(() => {
    // pagehide: đóng tab / rời trang. visibilitychange: chuyển tab, thu nhỏ cửa
    // sổ - trên mobile đây thường là tín hiệu cuối cùng nhận được trước khi bị
    // treo, nên không thể chỉ trông vào pagehide.
    const onHide = () => { if (document.visibilityState === "hidden") persist(); };
    window.addEventListener("pagehide", persist);
    document.addEventListener("visibilitychange", onHide);
    return () => {
      window.removeEventListener("pagehide", persist);
      document.removeEventListener("visibilitychange", onHide);
    };
  }, [persist]);

  // Một op: áp dụng tại chỗ trước, rồi đẩy lên server (nếu đang ở chế độ phòng).
  const dispatch = useCallback((op) => {
    setState((prev) => applyOp(prev, op));
    roomRef.current?.sendOp?.(op);
  }, []);

  // --- Nhận state từ server ---------------------------------------------------
  const subscribe = room?.subscribe;
  useEffect(() => {
    if (!subscribe) return undefined;
    return subscribe((msg) => {
      if (msg.type === "snapshot") {
        // msg.pending = op đã làm offline nhưng server chưa nhận. Đắp lại lên
        // trên, nếu không màn hình sẽ nháy mất việc vừa làm rồi mới hiện lại.
        setState(applyOps(normalize(msg.state), msg.pending));
      } else if (msg.type === "question") {
        setState((prev) => {
          const qid = clampQ(msg.qid);
          const norm = normalize({ numQuestions: prev.numQuestions, questions: { [qid]: msg.question } });
          return { ...prev, questions: { ...prev.questions, [qid]: norm.questions[qid] } };
        });
      } else if (msg.type === "meta") {
        setState((prev) => {
          const num = clampQ(msg.num_questions);
          return num === prev.numQuestions ? prev : { ...prev, numQuestions: num };
        });
      }
    });
  }, [subscribe]);

  const { numQuestions, questions } = state;
  const cur = useMemo(
    () => questions[current] || defaultQuestion(current),
    [questions, current]
  );
  const items = cur.items;

  // id -> hạng trong CÂU HIỆN TẠI. Map thay cho findIndex: lưới có thể tới hàng
  // nghìn ô, mỗi ô tra một lần -> O(n) thay vì O(n²).
  const rankMap = useMemo(() => new Map(items.map((it, i) => [it.id, i + 1])), [items]);

  // id -> câu nhỏ nhất đang chứa frame đó (để cảnh báo "frame này đã dùng ở câu
  // khác"). Ở chế độ phòng, cảnh báo này bắt được cả frame do đồng đội thêm.
  const questionMap = useMemo(() => {
    const m = new Map();
    const qids = Object.keys(questions).map(Number).sort((a, b) => a - b);
    for (const qid of qids) {
      for (const it of questions[qid].items) if (!m.has(it.id)) m.set(it.id, qid);
    }
    return m;
  }, [questions]);

  // Tóm tắt 1..N cho thanh/bảng chọn câu.
  const questionList = useMemo(
    () =>
      Array.from({ length: numQuestions }, (_, i) => {
        const qid = i + 1;
        const q = questions[qid];
        const taskType = q?.taskType || "kis";
        return {
          qid,
          count: q?.items.length || 0,
          taskType,
          queryId: q?.queryId || defaultQueryId(qid, taskType),
          queryIdLocked: q?.queryIdLocked === true,
          maxRows: q?.maxRows || MAX_ROWS,
          numEvents: q?.numEvents ?? null,
          queryText: q?.queryText || "",
        };
      }),
    [numQuestions, questions]
  );

  const totalCount = useMemo(
    () => questionList.reduce((s, q) => s + q.count, 0),
    [questionList]
  );

  // Câu nằm ngoài phạm vi 1..N nhưng vẫn còn đáp án (do người dùng giảm N).
  const hiddenWithData = useMemo(
    () =>
      Object.keys(questions)
        .map(Number)
        .filter((qid) => qid > numQuestions && questions[qid].items.length > 0)
        .sort((a, b) => a - b),
    [questions, numQuestions]
  );

  // --- Điều hướng câu (cục bộ, không đồng bộ) ---
  // numQuestions qua ref: setCurrent/step chỉ đọc nó lúc gọi, nên hai callback
  // này giữ nguyên tham chiếu và không làm QuestionSwitcher re-render theo.
  const numRef = useRef(numQuestions);
  numRef.current = numQuestions;

  const setCurrent = useCallback(
    (qid) => setCurrentRaw((prev) => {
      const q = clampQ(qid, numRef.current);
      return q === prev ? prev : q;
    }),
    [setCurrentRaw]
  );

  const step = useCallback(
    (dir) => setCurrentRaw((prev) => clampQ(prev + dir, numRef.current)),
    [setCurrentRaw]
  );

  // Số câu của đề thì CẢ NHÓM dùng chung.
  const setNumQuestions = useCallback(
    (n) => dispatch({ type: "set_num_questions", value: n }),
    [dispatch]
  );

  // Giữ con trỏ câu trong phạm vi khi ai đó (kể cả đồng đội) giảm số câu của đề.
  useEffect(() => {
    setCurrentRaw((prev) => (prev > numQuestions ? numQuestions : prev));
  }, [numQuestions, setCurrentRaw]);

  // --- Truy vấn ---
  const contains = useCallback((id) => rankMap.has(id), [rankMap]);
  const rankOf = useCallback((id) => rankMap.get(id) ?? null, [rankMap]);
  const questionOf = useCallback((id) => questionMap.get(id) ?? null, [questionMap]);
  const countOf = useCallback(
    (qid) => questions[clampQ(qid)]?.items.length || 0,
    [questions]
  );
  const itemsOf = useCallback(
    (qid) => questions[clampQ(qid)]?.items || [],
    [questions]
  );

  // Op luôn mang qid TUYỆT ĐỐI: server không biết máy nào đang ở câu nào.
  const currentRef = useRef(current);
  currentRef.current = current;
  const resolveQid = useCallback((qid) => clampQ(qid ?? currentRef.current, MAX_QUESTIONS), []);

  // --- Thao tác trên items (mặc định: câu hiện tại) ---
  const add = useCallback(
    (result, qid) => {
      if (!result || result.id == null) return;
      dispatch({ type: "add", qid: resolveQid(qid), item: toEntry(result, roomRef.current?.member) });
    },
    [dispatch, resolveQid]
  );

  const remove = useCallback(
    (id, qid) => dispatch({ type: "remove", qid: resolveQid(qid), id }),
    [dispatch, resolveQid]
  );

  // Thêm nếu chưa có, bỏ nếu đã có (tiện cho phím tắt/nút bấm).
  // Phải quy ra add/remove TẠI ĐÂY: server chỉ nhận op tất định, nếu không hai
  // người bấm cùng lúc sẽ toggle chồng nhau về đúng chỗ cũ.
  //
  // `questions` đi qua ref, cùng lý do với `room` ở trên: để trong deps thì
  // toggle đổi tham chiếu mỗi lần giỏ đổi - kể cả khi chỉ gõ một ký tự vào ô đáp
  // án - và nó là prop của ResultItem, component DUY NHẤT được memo trong repo.
  // Mất memo là mỗi phím gõ vẽ lại tới 1000 ô lưới kèm ảnh.
  const questionsRef = useRef(questions);
  questionsRef.current = questions;

  const toggle = useCallback(
    (result, qid) => {
      if (!result || result.id == null) return;
      const key = resolveQid(qid);
      const has = (questionsRef.current[key]?.items || []).some((it) => it.id === result.id);
      if (has) remove(result.id, key);
      else add(result, key);
    },
    [resolveQid, add, remove]
  );

  // Đổi hạng lên/xuống 1 bậc. dir = -1 (lên) | +1 (xuống).
  const move = useCallback(
    (id, dir, qid) => dispatch({ type: "move", qid: resolveQid(qid), id, dir }),
    [dispatch, resolveQid]
  );

  const reorder = useCallback(
    (from, to, qid) => dispatch({ type: "reorder", qid: resolveQid(qid), from, to }),
    [dispatch, resolveQid]
  );

  const setAnswerText = useCallback(
    (id, text, qid) => dispatch({ type: "set_answer", qid: resolveQid(qid), id, text }),
    [dispatch, resolveQid]
  );

  const setNote = useCallback(
    (id, text, qid) => dispatch({ type: "set_note", qid: resolveQid(qid), id, text }),
    [dispatch, resolveQid]
  );

  // Sửa tay số frame (keyframe thưa -> frame đúng thường không có ảnh để chọn).
  // Giá trị không phải số nguyên ≥ 0 bị reducer bỏ, nên gọi ẩu cũng không hỏng giỏ.
  const setFrame = useCallback(
    (id, value, qid) => dispatch({ type: "set_frame", qid: resolveQid(qid), id, value }),
    [dispatch, resolveQid]
  );

  // --- Cấu hình nộp của một câu ---
  const setTaskType = useCallback(
    (value, qid) => dispatch({ type: "set_task_type", qid: resolveQid(qid), value }),
    [dispatch, resolveQid]
  );

  const setQueryId = useCallback(
    (value, qid) => dispatch({ type: "set_query_id", qid: resolveQid(qid), value }),
    [dispatch, resolveQid]
  );

  const setMaxRows = useCallback(
    (value, qid) => dispatch({ type: "set_max_rows", qid: resolveQid(qid), value }),
    [dispatch, resolveQid]
  );

  // Số event của câu TRAKE; "" / 0 -> null (chưa khai).
  const setNumEvents = useCallback(
    (value, qid) => dispatch({ type: "set_num_events", qid: resolveQid(qid), value }),
    [dispatch, resolveQid]
  );

  const setQueryText = useCallback(
    (value, qid) => dispatch({ type: "set_query_text", qid: resolveQid(qid), value }),
    [dispatch, resolveQid]
  );

  /**
   * Nạp cấu hình từ gói truy vấn BTC.
   *   - mặc định (gộp): chỉ ghi đè phần CẤU HÌNH (task/queryId/numEvents/
   *     queryText) - items đã bỏ công tìm thì giữ nguyên;
   *   - `reset`: nhập lại TỪ ĐẦU cho vòng thi mới - xoá sạch câu cũ (cả đáp án
   *     lẫn câu nằm ngoài phạm vi numQuestions) rồi dựng lại đúng theo gói.
   * Gói là đề CHUNG của cả nhóm nên đi qua op - kể cả chế độ reset: một máy
   * bấm "nhập lại từ đầu" mà 4 máy kia vẫn giữ đề vòng trước thì mỗi máy nộp ra
   * một bộ file khác nhau.
   * @param {Array<{qid, taskType, queryId, queryText, numEvents}>} parsed
   * @param {{reset?: boolean}} [opts]
   */
  const importPackage = useCallback(
    (parsed, { reset = false } = {}) => {
      if (!parsed?.length) return;
      dispatch({ type: "import_package", items: parsed, reset });
      setCurrentRaw(clampQ(parsed[0].qid, MAX_QUESTIONS));
    },
    [dispatch, setCurrentRaw]
  );

  // --- Xoá ---
  const clearQuestion = useCallback(
    (qid) => dispatch({ type: "clear_question", qid: resolveQid(qid) }),
    [dispatch, resolveQid]
  );

  const clearAll = useCallback(() => dispatch({ type: "clear_all" }), [dispatch]);

  return {
    // câu hỏi
    numQuestions,
    setNumQuestions,
    current,
    setCurrent,
    next: useCallback(() => step(+1), [step]),
    prev: useCallback(() => step(-1), [step]),
    questionList,
    questions,
    totalCount,
    hiddenWithData,

    // câu hiện tại
    items,
    count: items.length,
    taskType: cur.taskType,
    queryId: cur.queryId,
    queryIdLocked: cur.queryIdLocked === true,
    maxRows: cur.maxRows,
    numEvents: cur.numEvents,
    queryText: cur.queryText,

    // truy vấn
    contains,
    rankOf,
    questionOf,
    countOf,
    itemsOf,

    // thao tác
    add,
    toggle,
    remove,
    move,
    reorder,
    setAnswerText,
    setNote,
    setFrame,
    setTaskType,
    setQueryId,
    setMaxRows,
    setNumEvents,
    setQueryText,
    importPackage,
    clearQuestion,
    clearAll,
  };
}
