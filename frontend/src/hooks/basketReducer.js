// src/hooks/basketReducer.js
// LOGIC THUẦN của giỏ đáp án, tách khỏi useAnswerBasket để DÙNG CHUNG hai chỗ:
//   1. client áp dụng lạc quan ngay khi bấm (UI không khựng chờ mạng);
//   2. server áp dụng lại đúng thứ tự nó nhận được, rồi phát ngược về mọi máy.
//
// ⚠ BẢN SAO PYTHON: backend/services/room_store.py - mọi thay đổi về TẬP OP hay
// NGỮ NGHĨA của một op ở đây PHẢI sửa song song bên đó, nếu không hai bên sẽ
// tính ra state khác nhau và giỏ của cả nhóm lệch nhau lúc thi.
//
// State chia sẻ: { numQuestions, questions }.
// `current` (câu đang làm) KHÔNG nằm ở đây - mỗi người làm một câu khác nhau
// nên nó là state cục bộ của từng máy (useAnswerBasket giữ riêng).
// đuôi .js tường minh để file này chạy được thẳng bằng `node` trong
// utils/submissionFormat.test.mjs; Vite vẫn resolve bình thường.
import { frameIndex } from "../utils/frameIndex.js";
import { MAX_ROWS, defaultQueryId, isAutoQueryId, retargetQueryId } from "../utils/submissionFormat.js";

export const MAX_QUESTIONS = 200;

export const clampQ = (n, max = MAX_QUESTIONS) =>
  Math.max(1, Math.min(max, Math.round(Number(n) || 1)));

export function defaultQuestion(qid) {
  return {
    taskType: "kis",
    queryId: defaultQueryId(qid, "kis"),
    // true = tên truy vấn do BTC phát (nạp từ gói đề), KHÔNG được tự đổi theo
    // task nữa: file nộp phải trùng tên truy vấn thì mới được chấm.
    queryIdLocked: false,
    maxRows: MAX_ROWS,
    // Số event của đề TRAKE. null = chưa khai -> bước kiểm tra sẽ chặn nộp,
    // vì không biết cắt chuỗi frame ở đâu.
    numEvents: null,
    // Nội dung đề BTC phát (điền khi nhập gói truy vấn), để đọc ngay trong app.
    queryText: "",
    items: [],
  };
}

// Chuẩn hoá một kết quả search -> một mục trong giỏ.
// `by` = { id, name } của người thêm; ghi lại để cả nhóm biết frame này của ai.
export function toEntry(result, by) {
  const entry = {
    id: result.id,
    video_name: result.video_name,
    frame_name: result.frame_name,
    frame_idx: frameIndex(result),
    timestamp_ms: result.timestamp_ms ?? null,
    fps: result.fps ?? null,
    frame_url: result.frame_url,
    video_url: result.video_url,
    answer: "", // dùng cho task Q&A
    note: "",
    added_by: by?.id ?? null,
    added_by_name: by?.name ?? null,
    added_at: Date.now(),
  };
  // Mục thêm THỦ CÔNG (ManualFrameAdd) mang sẵn frame_idx0 = số của keyframe
  // gần nhất, tức là frame của CÁI ẢNH đang hiện trong giỏ. Chép qua để giỏ vẽ
  // đúng badge Δ - ảnh và số frame sắp nộp không phải một, và người dùng phải
  // thấy điều đó. Mục thêm bằng nút + thì không có trường này (ảnh chính là
  // frame sẽ nộp), nên chỉ chép khi có.
  if (result.frame_idx0 != null) entry.frame_idx0 = result.frame_idx0;
  return entry;
}

export function normalize(raw) {
  const questions = {};
  for (const [key, q] of Object.entries(raw?.questions || {})) {
    const qid = Number(key);
    if (!Number.isInteger(qid) || qid < 1) continue;
    const base = defaultQuestion(qid);
    questions[qid] = {
      taskType: typeof q?.taskType === "string" ? q.taskType : base.taskType,
      queryId: typeof q?.queryId === "string" ? q.queryId : base.queryId,
      queryIdLocked: q?.queryIdLocked === true,
      // Kẹp trần MAX_ROWS: giỏ lưu từ phiên bản cũ có thể đang giữ maxRows > 100.
      maxRows: Number(q?.maxRows) > 0 ? Math.min(Number(q.maxRows), MAX_ROWS) : base.maxRows,
      numEvents: Number(q?.numEvents) > 0 ? Math.round(Number(q.numEvents)) : null,
      queryText: typeof q?.queryText === "string" ? q.queryText : "",
      items: Array.isArray(q?.items) ? q.items.filter((it) => it && it.id != null) : [],
    };
  }
  return { numQuestions: clampQ(raw?.numQuestions ?? 1), questions };
}

// Sửa một câu mà không đụng tới các câu khác. fn(q) trả về chính q -> không đổi state.
function patchQuestion(state, qid, fn) {
  const key = clampQ(qid, MAX_QUESTIONS);
  const q = state.questions[key] || defaultQuestion(key);
  const next = fn(q, key);
  if (next === q) return state;
  return { ...state, questions: { ...state.questions, [key]: next } };
}

const patchItems = (state, qid, fn) =>
  patchQuestion(state, qid, (q) => {
    const items = fn(q.items);
    return items === q.items ? q : { ...q, items };
  });

/**
 * Áp dụng MỘT op lên state. Thuần: cùng (state, op) luôn ra cùng kết quả, và
 * trả về CHÍNH `state` khi op không đổi gì (để React bỏ qua render).
 *
 * Mọi op đều mang sẵn `qid` tuyệt đối - KHÔNG bao giờ ngầm hiểu "câu hiện tại",
 * vì server không biết máy nào đang ở câu nào.
 */
export function applyOp(state, op) {
  if (!op || typeof op.type !== "string") return state;
  switch (op.type) {
    // add idempotent theo id: gửi lại op sau khi mất mạng cũng không nhân đôi.
    case "add":
      if (!op.item || op.item.id == null) return state;
      return patchItems(state, op.qid, (list) =>
        list.some((it) => it.id === op.item.id) ? list : [...list, op.item]
      );

    case "remove":
      return patchItems(state, op.qid, (list) => {
        const next = list.filter((it) => it.id !== op.id);
        return next.length === list.length ? list : next;
      });

    // Đổi hạng lên/xuống 1 bậc. dir = -1 (lên) | +1 (xuống).
    case "move":
      return patchItems(state, op.qid, (list) => {
        const idx = list.findIndex((it) => it.id === op.id);
        if (idx === -1) return list;
        const target = idx + op.dir;
        if (target < 0 || target >= list.length) return list;
        const next = [...list];
        [next[idx], next[target]] = [next[target], next[idx]];
        return next;
      });

    case "reorder":
      return patchItems(state, op.qid, (list) => {
        const { from, to } = op;
        if (from === to || from < 0 || to < 0 || from >= list.length || to >= list.length) return list;
        const next = [...list];
        const [moved] = next.splice(from, 1);
        next.splice(to, 0, moved);
        return next;
      });

    case "set_answer":
      return patchItems(state, op.qid, (list) => {
        if (!list.some((it) => it.id === op.id && it.answer !== op.text)) return list;
        return list.map((it) => (it.id === op.id ? { ...it, answer: op.text } : it));
      });

    case "set_note":
      return patchItems(state, op.qid, (list) => {
        if (!list.some((it) => it.id === op.id && it.note !== op.text)) return list;
        return list.map((it) => (it.id === op.id ? { ...it, note: op.text } : it));
      });

    /**
     * Sửa TAY số frame của một mục.
     *
     * Cần vì keyframe trong index là THƯA: khoảnh khắc đúng của đáp án thường
     * rơi vào một frame không có keyframe nào, nên không thể chọn nó từ lưới
     * kết quả hay từ cửa sổ chuỗi frame - chỉ còn cách xem video rồi gõ số.
     *
     * Ba điểm phải giữ đúng, nếu không mục sửa tay sẽ nói dối:
     *  - timestamp_ms tính lại theo fps: mọi nút "mở video" đều tua theo trường
     *    này, để nguyên là lần sau mở ra vẫn về đúng chỗ CŨ, không phải frame
     *    vừa chốt;
     *  - frame_name GIỮ NGUYÊN: /frame_neighbors tra theo tên keyframe, đổi nó
     *    là hỏng nút "chuỗi"; thumbnail cũng vẫn là ảnh của keyframe gốc;
     *  - frame_idx0 chỉ ghi ở LẦN SỬA ĐẦU (mốc để hoàn tác). Ghi lại mỗi lần
     *    sửa thì sửa hai lần là mất luôn đường về số máy tự tính.
     * ⚠ Mirror: nhánh "set_frame" trong backend/services/room_store.py.
     */
    case "set_frame": {
      // Giá trị rác không bao giờ được vào state DÙNG CHUNG: BTC so khớp
      // frame_idx dưới dạng số nguyên, một chuỗi lạ lọt vào là mục đó bị loại
      // âm thầm khỏi file nộp.
      //
      // Chặn null/""/boolean TRƯỚC Number(): Number(null) và Number("") đều ra
      // 0 - một frame_idx trông hoàn toàn hợp lệ. Ô nhập để trống mà lọt qua
      // đây là frame bị đặt về 0 chứ không phải bị bỏ qua. (Bên Python float()
      // ném lỗi cho cả hai nên không cần nhánh này - chỉ JS mới lỏng.)
      if (op.value == null || op.value === "" || typeof op.value === "boolean") return state;
      const n = Math.round(Number(op.value));
      if (!Number.isInteger(n) || n < 0) return state;
      return patchItems(state, op.qid, (list) => {
        const it = list.find((x) => x.id === op.id);
        if (!it || it.frame_idx === n) return list;
        const next = { ...it, frame_idx: n };
        if (!("frame_idx0" in it)) next.frame_idx0 = it.frame_idx ?? null;
        if (Number(it.fps) > 0) next.timestamp_ms = Math.round((n / Number(it.fps)) * 1000);
        return list.map((x) => (x.id === op.id ? next : x));
      });
    }

    // Đổi task -> tên file nộp phải đổi theo (query-3-qa.csv chứ không còn -kis).
    // Chỉ tự sửa khi queryId vẫn đang là chuỗi do app sinh VÀ không phải tên BTC
    // phát: "query-3-qa" nạp từ gói đề cũng khớp mẫu tự sinh, tự đổi nó thành
    // "query-3-kis" là đổi luôn tên file nộp sang một truy vấn không tồn tại.
    // Người dùng gõ tay thì cũng giữ nguyên.
    case "set_task_type":
      return patchQuestion(state, op.qid, (q, key) => {
        if (q.taskType === op.value) return q;
        const next = { ...q, taskType: op.value };
        if (isAutoQueryId(q.queryId) && !q.queryIdLocked) {
          next.queryId = retargetQueryId(q.queryId, key, op.value);
        }
        return next;
      });

    // Sửa tay -> bỏ khoá: từ giờ người dùng tự chịu trách nhiệm cái tên đó.
    case "set_query_id":
      return patchQuestion(state, op.qid, (q) =>
        q.queryId === op.value ? q : { ...q, queryId: op.value, queryIdLocked: false }
      );

    // Trần cứng MAX_ROWS: BTC chỉ nhận tối đa 100 dòng mỗi file.
    case "set_max_rows": {
      const n = Math.min(MAX_ROWS, Math.max(1, Number(op.value) || 1));
      return patchQuestion(state, op.qid, (q) => (q.maxRows === n ? q : { ...q, maxRows: n }));
    }

    // Số event của câu TRAKE; "" / 0 -> null (chưa khai).
    case "set_num_events": {
      const raw = Math.round(Number(op.value) || 0);
      const n = raw > 0 ? raw : null;
      return patchQuestion(state, op.qid, (q) => (q.numEvents === n ? q : { ...q, numEvents: n }));
    }

    case "set_query_text":
      return patchQuestion(state, op.qid, (q) => (q.queryText === op.value ? q : { ...q, queryText: op.value }));

    // Nạp cấu hình từ gói truy vấn BTC. Hai chế độ, khác nhau ở chỗ ĐỀ CŨ còn
    // hay mất:
    //   * gộp (mặc định): chỉ ghi đè phần CẤU HÌNH (task/queryId/numEvents/
    //     queryText) - items đã bỏ công tìm thì giữ nguyên. Dùng khi BTC phát
    //     bù một file hoặc sửa đề giữa vòng.
    //   * op.reset === true ("nhập lại từ đầu"): gói mới là ĐỀ CỦA VÒNG KHÁC,
    //     xoá sạch questions rồi dựng lại đúng theo gói. Phải xoá cả object chứ
    //     không chỉ hạ numQuestions: câu ngoài phạm vi vẫn nằm nguyên trong
    //     state (xem hiddenWithData) và sẽ sống lại kèm đáp án vòng trước ngay
    //     khi vòng sau có nhiều câu hơn.
    case "import_package": {
      const parsed = Array.isArray(op.items) ? op.items : [];
      if (!parsed.length) return state;
      const reset = op.reset === true;
      const questions = reset ? {} : { ...state.questions };
      let maxQid = reset ? 0 : state.numQuestions;
      for (const p of parsed) {
        const key = clampQ(p.qid);
        const base = questions[key] || defaultQuestion(key);
        questions[key] = {
          ...base,
          taskType: p.taskType || base.taskType,
          queryId: p.queryId || base.queryId,
          // Tên này là của BTC -> khoá lại, không cho set_task_type đổi.
          queryIdLocked: Boolean(p.queryId),
          queryText: p.queryText ?? base.queryText,
          numEvents: p.numEvents ?? base.numEvents,
        };
        if (key > maxQid) maxQid = key;
      }
      return { ...state, numQuestions: clampQ(maxQid), questions };
    }

    case "clear_question":
      return patchItems(state, op.qid, (list) => (list.length ? [] : list));

    case "clear_all":
      return Object.keys(state.questions).length ? { ...state, questions: {} } : state;

    case "set_num_questions": {
      const num = clampQ(op.value);
      return num === state.numQuestions ? state : { ...state, numQuestions: num };
    }

    default:
      return state;
  }
}

export function applyOps(state, ops) {
  return (ops || []).reduce(applyOp, state);
}
