// src/utils/submissionValidate.js
// Kiểm tra giỏ đáp án TRƯỚC KHI xuất file - bắt đúng những lỗi BTC liệt kê
// trong hướng dẫn (nộp sai định dạng vẫn tính là 1 trong 3 lượt nộp, nên rẻ
// nhất là chặn ngay tại đây).
//
// Hàm thuần, không phụ thuộc React -> test được bằng node, và UI chỉ việc vẽ.
//
// level "error" = chắc chắn hỏng bài (chặn nút tải, có lối vượt thủ công);
// level "warn"  = vẫn nộp được nhưng có thể đang phí dòng / phí lượt.
import {
  MAX_ROWS,
  MAX_ANSWER_LEN,
  TASK_SHORT,
  charLen,
  chunkTrake,
  cleanEntries,
  isValidFrameIdx,
  normalizeAnswer,
  suggestFilename,
  taskFromQueryId,
  // đuôi .js tường minh để chạy được thẳng bằng `node` (xem submissionFormat.test.mjs)
  // mà không cần thêm test-runner; Vite vẫn resolve bình thường.
} from "./submissionFormat.js";

const err = (qid, msg) => ({ qid, level: "error", msg });
const warn = (qid, msg) => ({ qid, level: "warn", msg });

// Tên video phải là "L01_V028" - không đuôi .mp4, không khoảng trắng.
const VIDEO_NAME_RE = /^L\d+_V\d+$/i;

function checkVideoNames(q, out) {
  const bad = new Set();
  const odd = new Set();
  for (const it of q.items) {
    const v = String(it.video_name || "");
    if (/\.mp4$/i.test(v) || /\s/.test(v) || !v) bad.add(v || "(rỗng)");
    else if (!VIDEO_NAME_RE.test(v)) odd.add(v);
  }
  for (const v of bad) {
    out.push(err(q.qid, `Tên video không hợp lệ: "${v}" - bỏ đuôi .mp4 và khoảng trắng`));
  }
  // Không chặn: bộ dữ liệu có thể đặt tên khác, nhưng lệch mẫu L**_V*** thường
  // là dấu hiệu frame lấy nhầm nguồn.
  for (const v of odd) {
    out.push(warn(q.qid, `Tên video "${v}" không theo mẫu L01_V028 - kiểm tra lại`));
  }
}

function checkFrameIdx(q, out) {
  const missing = q.items.filter((it) => it.frame_idx == null).length;
  if (missing > 0) {
    // toCSV lọc âm thầm các mục này -> số dòng thực tế hụt so với giỏ.
    out.push(err(q.qid, `${missing} frame không đọc được frame_idx - sẽ bị loại khỏi file nộp`));
  }
  // BTC so Frame ID dưới dạng SỐ NGUYÊN; giá trị thực/chuỗi lạ cũng bị loại khỏi
  // file y như thiếu, nên phải báo riêng kèm ví dụ để còn lần ra frame nào.
  const bad = q.items.filter((it) => it.frame_idx != null && !isValidFrameIdx(it.frame_idx));
  if (bad.length > 0) {
    out.push(err(
      q.qid,
      `${bad.length} frame có frame_idx không phải số nguyên (vd "${bad[0].frame_idx}") - sẽ bị loại khỏi file nộp`
    ));
  }
}

function checkQa(q, out) {
  const empty = q.items.filter((it) => !normalizeAnswer(it.answer)).length;
  if (empty > 0) out.push(err(q.qid, `${empty} dòng chưa có câu trả lời`));

  // Đếm trên ĐÚNG chuỗi toCSV sẽ ghi ra, nếu không thì con số báo ở đây và số
  // ký tự thật trong file lệch nhau.
  const tooLong = q.items.filter(
    (it) => charLen(normalizeAnswer(it.answer)) > MAX_ANSWER_LEN
  ).length;
  if (tooLong > 0) {
    out.push(err(q.qid, `${tooLong} câu trả lời vượt ${MAX_ANSWER_LEN} ký tự`));
  }

  // BTC giữ nguyên khoảng trắng đầu/cuối khi so đáp án. toCSV đã tự cắt, nhưng
  // vẫn phải nói ra: người dùng cần biết cái mình gõ và cái được nộp khác nhau.
  const padded = q.items.filter((it) => {
    const a = String(it.answer || "");
    return a && a !== a.trim();
  }).length;
  if (padded > 0) {
    out.push(warn(q.qid, `${padded} câu trả lời có khoảng trắng thừa ở đầu/cuối - sẽ được cắt khi xuất file`));
  }

  // Xuống dòng trong đáp án (dán từ đề/chat): toCSV thay bằng dấu cách để một
  // dòng CSV không trải trên hai dòng vật lý. Đổi nội dung đáp án là chuyện phải
  // báo, vì BTC so khớp chuỗi.
  const multiline = q.items.filter((it) => /[\r\n\t]/.test(String(it.answer || ""))).length;
  if (multiline > 0) {
    out.push(warn(
      q.qid,
      `${multiline} câu trả lời có xuống dòng - sẽ thay bằng dấu cách khi xuất file, kiểm tra lại nội dung`
    ));
  }

  // Ví dụ trong thể lệ in answer kèm ngoặc kép ("5"), rất dễ bị chép nguyên vào
  // ô nhập; khi đó dấu ngoặc thành MỘT PHẦN của đáp án và sai khi so chuỗi.
  const quoted = q.items.filter((it) => {
    const a = String(it.answer || "").trim();
    return a.length >= 2 && a.startsWith('"') && a.endsWith('"');
  }).length;
  if (quoted > 0) {
    out.push(warn(
      q.qid,
      `${quoted} câu trả lời đang bọc trong dấu ngoặc kép - gõ thẳng nội dung, file nộp tự thêm khi cần`
    ));
  }
}

function checkTrake(q, out) {
  const n = Math.round(Number(q.numEvents) || 0);
  if (!n) {
    out.push(err(q.qid, "Chưa khai số event của đề - không biết cắt chuỗi ở đâu"));
    return;
  }
  // Cắt trên CÙNG danh sách mà toCSV sẽ ghi ra, nếu không thì số hiệu "Đáp án #k"
  // ở đây không chỉ đúng dòng nào trong file. Mục bị lọc đã được checkFrameIdx
  // báo lỗi riêng nên không mất cảnh báo nào.
  const groups = chunkTrake(cleanEntries(q.items), n);
  groups.forEach((g, i) => {
    const label = `Đáp án #${i + 1}`;
    if (g.length !== n) {
      out.push(err(q.qid, `${label} mới có ${g.length}/${n} frame`));
      return; // thiếu frame thì các kiểm tra dưới không còn ý nghĩa
    }
    const videos = new Set(g.map((it) => it.video_name));
    if (videos.size > 1) {
      out.push(err(q.qid, `${label} lẫn ${videos.size} video khác nhau - một chuỗi phải cùng một video`));
    }
    const idxs = g.map((it) => it.frame_idx);
    const ascending = idxs.every((v, k) => k === 0 || v > idxs[k - 1]);
    if (!ascending) {
      out.push(err(q.qid, `${label} có frame không tăng dần - các event phải đúng thứ tự thời gian`));
    }
  });
}

// Trùng trong cùng một câu: không sai format nhưng phí dòng trong hạn mức 100.
//
// Đơn vị so trùng phải là MỘT DÒNG CSV, không phải một frame. Với TRAKE, hai ứng
// viên khác nhau hoàn toàn có quyền dùng chung frame của event 1 - so theo frame
// thì vừa báo nhầm, vừa bỏ sót đúng thứ đáng báo là hai chuỗi giống hệt nhau.
function checkDuplicates(q, out) {
  const clean = cleanEntries(q.items);
  const keys =
    q.taskType === "trake"
      ? (Number(q.numEvents) > 0 ? chunkTrake(clean, q.numEvents) : [])
          .filter((g) => g.length === Math.round(Number(q.numEvents)))
          .map((g) => `${g[0].video_name}#${g.map((it) => it.frame_idx).join(",")}`)
      : clean.map((it) => `${it.video_name}#${it.frame_idx}`);

  const seen = new Set();
  let dup = 0;
  for (const key of keys) {
    if (seen.has(key)) dup += 1;
    else seen.add(key);
  }
  if (dup > 0) {
    const what = q.taskType === "trake" ? "chuỗi trùng nhau hoàn toàn" : "dòng trùng (cùng video + cùng frame)";
    out.push(warn(q.qid, `${dup} ${what} - đang phí hạn mức`));
  }
}

function checkRowCount(q, out) {
  const clean = cleanEntries(q.items);
  if (q.taskType === "trake" && !(Number(q.numEvents) > 0)) return; // chưa biết cắt ở đâu -> chưa đếm được dòng
  const rows = q.taskType === "trake" ? chunkTrake(clean, q.numEvents).length : clean.length;
  const cap = Math.min(Number(q.maxRows) || MAX_ROWS, MAX_ROWS);
  if (rows > cap) {
    out.push(warn(q.qid, `${rows} dòng, sẽ bị cắt còn ${cap}`));
  }
}

/**
 * @param {Array} questions - [{ qid, taskType, queryId, maxRows, numEvents, items }]
 *   (đúng shape mà SubmissionPanel đã dựng từ basket).
 * @returns {Array<{qid:number, level:"error"|"warn", msg:string}>}
 */
export function validateSubmission(questions) {
  const out = [];
  const list = (questions || []).map((q) => ({ ...q, items: q.items || [] }));

  // --- Kiểm tra xuyên câu ---
  const byFilename = new Map();
  const frameOwners = new Map(); // id -> [qid]
  for (const q of list) {
    if (!q.items.length) continue;
    const fn = suggestFilename(q.queryId || `query-${q.qid}-${q.taskType}`);
    if (!byFilename.has(fn)) byFilename.set(fn, []);
    byFilename.get(fn).push(q.qid);

    for (const it of q.items) {
      if (!frameOwners.has(it.id)) frameOwners.set(it.id, []);
      const owners = frameOwners.get(it.id);
      if (!owners.includes(q.qid)) owners.push(q.qid);
    }
  }
  for (const [fn, qids] of byFilename) {
    if (qids.length > 1) {
      out.push(err(qids[0], `Câu ${qids.join(", ")} cùng ghi ra "${fn}" - đặt Query ID khác nhau`));
    }
  }
  const shared = new Map(); // qid -> số frame dùng chung
  for (const owners of frameOwners.values()) {
    if (owners.length < 2) continue;
    for (const qid of owners) shared.set(qid, (shared.get(qid) || 0) + 1);
  }
  for (const [qid, nShared] of shared) {
    const others = list
      .filter((q) => q.qid !== qid && q.items.some((it) => frameOwners.get(it.id)?.includes(qid)))
      .map((q) => q.qid);
    out.push(warn(qid, `${nShared} frame đang dùng chung với câu ${others.join(", ")}`));
  }

  // --- Kiểm tra từng câu ---
  for (const q of list) {
    if (!q.items.length) {
      out.push(warn(q.qid, "Chưa có đáp án - câu này sẽ không có file trong zip"));
      continue;
    }
    checkVideoNames(q, out);
    checkFrameIdx(q, out);
    checkRowCount(q, out);
    checkDuplicates(q, out);
    if (q.taskType === "qa") checkQa(q, out);
    if (q.taskType === "trake") checkTrake(q, out);

    // Không mục nào xuất được -> file rỗng. buildExports bỏ file này khỏi zip,
    // nghĩa là câu coi như bỏ trắng; phải báo chứ không để lẳng lặng biến mất.
    if (cleanEntries(q.items).length === 0) {
      out.push(err(q.qid, `${q.items.length} đáp án nhưng không mục nào xuất được ra CSV - câu này sẽ không có file trong zip`));
    }

    const idTask = taskFromQueryId(q.queryId);
    if (!idTask) {
      out.push(
        warn(q.qid, `Query ID "${q.queryId}" không theo mẫu query-<số>-<task> của BTC`)
      );
    } else if (idTask !== q.taskType) {
      // Tên file nói một đằng, số cột trong file một nẻo: file vẫn là CSV hợp lệ
      // nên không có gì khác bắt được, mà BTC chấm theo đúng tên truy vấn.
      out.push(err(
        q.qid,
        `File "${suggestFilename(q.queryId)}" là truy vấn ${TASK_SHORT[idTask]} nhưng câu đang đặt ${TASK_SHORT[q.taskType] || q.taskType} - nội dung sẽ sai số cột`
      ));
    }
  }

  return out;
}

// Gom theo câu để UI vẽ một dòng cho mỗi câu.
export function groupIssues(issues) {
  const m = new Map();
  for (const i of issues || []) {
    if (!m.has(i.qid)) m.set(i.qid, []);
    m.get(i.qid).push(i);
  }
  return m;
}

export const hasErrors = (issues) => (issues || []).some((i) => i.level === "error");
