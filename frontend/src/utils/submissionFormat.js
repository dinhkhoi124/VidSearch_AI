// src/utils/submissionFormat.js
// NƠI DUY NHẤT định nghĩa định dạng nộp bài - theo SPEC CHÍNH THỨC BTC AIC 2026.
//
// Quy tắc chung: UTF-8, ngăn cách bằng dấu phẩy, KHÔNG có dòng header, tối đa
// 100 dòng/file. Ba dạng truy vấn:
//   - KIS   : "video_name,frame_idx"                      (xếp theo độ tin cậy giảm dần)
//   - Q&A   : "video_name,frame_idx,answer"               (answer ≤ 100 ký tự)
//   - TRAKE : "video_name,frame_1,frame_2,...,frame_N"    (đúng N event của đề)
//
// TRAKE - điểm dễ sai nhất: mỗi DÒNG là một ứng viên độc lập, và spec cho phép
// CÙNG MỘT VIDEO xuất hiện ở nhiều dòng (ví dụ của BTC có L10_V001 hai lần).
// Vì vậy các frame trong giỏ được chia khối tuần tự theo numEvents - khối
// [0..N-1] là ứng viên 1, [N..2N-1] là ứng viên 2… - CHỨ KHÔNG gộp theo
// video_name (gộp theo video thì không thể nộp 2 chuỗi cùng video, và số frame
// mỗi dòng sẽ không khớp N).
//
// Nộp bài: một file .zip chứa thư mục "submission/" ở gốc, bên trong là các
// file .csv đặt tên đúng bằng tên truy vấn của BTC (query-1-kis.csv, ...).

export const TASK_TYPES = ["kis", "qa", "trake"];

export const TASK_LABEL = {
  kis: "KIS (1 frame)",
  qa: "Q&A (frame + câu trả lời)",
  trake: "TRAKE (chuỗi frame)",
};

// Nhãn ngắn cho các ô chọn câu (chật chỗ).
export const TASK_SHORT = { kis: "KIS", qa: "Q&A", trake: "TRAKE" };

// Giới hạn cứng của BTC - dùng chung cho cả UI lẫn bước kiểm tra.
export const MAX_ROWS = 100;
export const MAX_ANSWER_LEN = 100;

// Tên truy vấn do BTC đặt. Dạng tối giản là "query-<số>-<task>", nhưng gói thật
// còn chèn ĐỢT THI vào giữa: "query-p1-15-qa". Cho phép bao nhiêu đoạn tiền tố
// cũng được, miễn mỗi đoạn BẮT ĐẦU BẰNG CHỮ - nếu không thì "p1" và số câu nhập
// nhằng nhau và không biết câu 1 hay câu 15.
//   query-15-qa | query-p1-15-qa | query-vong2-p1-15-trake
// Dùng để (a) sinh mặc định, (b) biết một queryId có phải do app tự sinh không
// -> còn tự cập nhật được khi người dùng đổi task; người dùng đã sửa tay thì tôn
// trọng, không ghi đè. (c) đối chiếu task của câu với task ghi trong tên file.
export const QUERY_ID_RE = /^query-((?:[a-z][a-z0-9]*-)*)(\d+)-(kis|qa|trake)$/i;

/**
 * Bóc tiền tố đợt + số câu + loại task từ một tên truy vấn.
 * NƠI DUY NHẤT hiểu quy ước đặt tên của BTC - utils/queryPackage.js đọc tên file
 * gói đề cũng gọi lại hàm này, để hai chỗ không bao giờ hiểu khác nhau.
 * `prefix` gồm cả dấu gạch cuối ("p1-") hoặc rỗng.
 * @returns {{qid:number, taskType:string, prefix:string} | null}
 */
export function parseQueryId(queryId) {
  const m = String(queryId || "").trim().match(QUERY_ID_RE);
  if (!m) return null;
  const qid = parseInt(m[2], 10);
  if (!Number.isInteger(qid) || qid < 1) return null;
  return { qid, taskType: m[3].toLowerCase(), prefix: m[1] };
}

export function defaultQueryId(qid, taskType) {
  return `query-${qid}-${taskType}`;
}

export function isAutoQueryId(queryId) {
  return parseQueryId(queryId) !== null;
}

/**
 * Sinh lại tên truy vấn tự động cho câu `qid` khi đổi task, GIỮ tiền tố đợt.
 * Số câu và task luôn bám câu hiện tại (tên tự sinh phải chỉ đúng câu nó thuộc
 * về), nhưng "p1" thì phải giữ: gói thật đặt tên "query-p1-15-qa", nuốt mất
 * tiền tố là nộp file mang tên một truy vấn không tồn tại.
 * ⚠ Mirror: _retarget_query_id trong backend/services/room_store.py.
 */
export function retargetQueryId(queryId, qid, taskType) {
  const prefix = parseQueryId(queryId)?.prefix || "";
  return `query-${prefix}${qid}-${taskType}`;
}

// Hậu tố task nằm ngay trong tên truy vấn BTC phát ("query-3-qa" -> "qa").
// Dùng để phát hiện tên file và loại task của câu đang nói hai chuyện khác nhau.
export function taskFromQueryId(queryId) {
  return parseQueryId(queryId)?.taskType ?? null;
}

// Đếm ký tự theo CODE POINT, không theo đơn vị UTF-16: "ừ" tổ hợp hay emoji chỉ
// tính 1. Trần 100 ký tự của BTC dùng cách đếm này mới không báo lố.
export const charLen = (s) => [...String(s ?? "")].length;

/**
 * Chuẩn hoá một câu trả lời Q&A về đúng thứ sẽ nằm trong file.
 *
 * Xuống dòng/tab phải biến thành dấu cách: theo RFC thì bọc ngoặc kép là hợp
 * lệ, nhưng khi đó MỘT dòng CSV trải trên hai dòng vật lý - chương trình chấm
 * đọc từng dòng sẽ thấy hai bản ghi rách thay vì một. Ký tự này gần như luôn do
 * dán nhầm từ đề hoặc từ chat, không bao giờ là một phần của đáp án.
 *
 * Trim vì BTC so khớp CHUỖI và giữ nguyên khoảng trắng đầu/cuối: " Vạn Ninh "
 * là một đáp án khác.
 * PHẢI dùng chung giữa toCSV và bước kiểm tra, nếu không số ký tự báo cho người
 * dùng sẽ khác số ký tự thật trong file.
 */
export function normalizeAnswer(value) {
  return String(value ?? "").replace(/[\r\n\t]+/g, " ").trim();
}

// CSV escaping cho trường answer (có thể chứa dấu phẩy / ngoặc kép / xuống dòng).
// Theo spec: ngoặc kép chỉ BẮT BUỘC khi có ký tự đặc biệt; ngoặc kép bên trong
// được escape bằng cách nhân đôi.
function csvCell(value) {
  const s = value == null ? "" : String(value);
  if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

/**
 * Chiều NGƯỢC của csvCell: tách một dòng CSV thành các trường.
 *
 * Đặt ngay cạnh csvCell để hai chiều ghi/đọc không trôi khỏi nhau. Dùng cho màn
 * XEM TRƯỚC: chỉ khi tách lại đúng luật CSV mới thấy được số cột mà chương
 * trình chấm thật sự đọc ra - một đáp án Q&A có dấu phẩy nhìn ở dạng văn bản
 * thô thì y như đang có ba cột, nhưng phải bọc ngoặc kép mới đúng là ba.
 *
 * KHÔNG dùng để sinh file nộp; chỉ để đọc lại thứ toCSV vừa sinh ra.
 * @param {string} line - một dòng, không chứa \n.
 * @returns {string[]}
 */
export function parseCsvLine(line) {
  const out = [];
  const s = String(line ?? "");
  let cur = "";
  let quoted = false;
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (quoted) {
      // "" bên trong trường có ngoặc kép = một dấu ngoặc kép thật.
      if (ch === '"' && s[i + 1] === '"') { cur += '"'; i++; }
      else if (ch === '"') quoted = false;
      else cur += ch;
    } else if (ch === '"' && cur === "") {
      quoted = true;
    } else if (ch === ",") {
      out.push(cur);
      cur = "";
    } else {
      cur += ch;
    }
  }
  out.push(cur);
  return out;
}

/**
 * Chia items của câu TRAKE thành các ứng viên, mỗi ứng viên đúng numEvents frame.
 * Khối cuối có thể THIẾU frame - trả về nguyên trạng để bước kiểm tra bắt lỗi,
 * chứ không âm thầm vứt đi.
 * @returns {Array<Array>} mảng các khối item.
 */
// BTC so sánh Frame ID "dưới dạng số nguyên" -> một frame_idx là số thực, chuỗi
// lạ hay NaN là mục KHÔNG xuất được, chứ không phải mục xuất ra rồi hỏng.
export function isValidFrameIdx(value) {
  if (value == null || value === "") return false;
  const n = Number(value);
  return Number.isInteger(n) && n >= 0;
}

/**
 * Bỏ các mục không xuất được ra CSV (thiếu video_name, hoặc frame_idx không
 * phải số nguyên ≥ 0).
 * PHẢI dùng chung giữa toCSV và bước kiểm tra: nếu hai bên cắt khối TRAKE trên
 * hai danh sách khác nhau thì ranh giới "Đáp án #k" báo cho người dùng sẽ lệch
 * với file thật, và mọi ứng viên phía sau bị dịch đi một frame.
 */
export function cleanEntries(entries) {
  return (entries || []).filter(
    (e) => e && e.video_name != null && isValidFrameIdx(e.frame_idx)
  );
}

// Frame ID luôn ghi ra dạng SỐ NGUYÊN. Giỏ có thể đang giữ chuỗi "1234.0" (dữ
// liệu cũ, hoặc metadata đọc từ nguồn khác): isValidFrameIdx cho qua vì trị số
// vẫn nguyên, nhưng ghi thẳng chuỗi đó thì file nộp có "1234.0" trong khi BTC
// so sánh dưới dạng số nguyên -> lệch một frame là mất điểm cả dòng.
function frameCell(value) {
  return String(Number(value));
}

export function chunkTrake(items, numEvents) {
  const n = Math.max(1, Math.round(Number(numEvents) || 0));
  const list = items || [];
  if (!n) return list.length ? [list] : [];
  const out = [];
  for (let i = 0; i < list.length; i += n) out.push(list.slice(i, i + n));
  return out;
}

/**
 * Sinh nội dung CSV để nộp.
 * @param {Array} entries - các mục trong giỏ (thứ tự = thứ hạng).
 * @param {"kis"|"qa"|"trake"} taskType
 * @param {{maxRows?: number, numEvents?: number}} opts
 * @returns {string}
 */
export function toCSV(entries, taskType, opts = {}) {
  const { maxRows = MAX_ROWS, numEvents } = opts;
  const cap = Math.min(Number(maxRows) || MAX_ROWS, MAX_ROWS);
  const clean = cleanEntries(entries);

  if (taskType === "trake") {
    // Chưa khai số event mà vẫn cắt thì chunkTrake rơi về n=1: mỗi frame một
    // dòng, file sai hoàn toàn nhưng trông vẫn như CSV hợp lệ. Ném lỗi để đường
    // "vẫn tải xuống dù còn lỗi" không đi qua được chỗ này.
    if (!(Number(numEvents) > 0)) {
      throw new Error("Câu TRAKE chưa khai số event - không biết cắt chuỗi frame ở đâu");
    }
    // Mỗi khối = một dòng. maxRows cắt theo SỐ ỨNG VIÊN (số dòng), không phải số frame.
    return chunkTrake(clean, numEvents)
      .slice(0, cap)
      .map((group) =>
        [group[0].video_name, ...group.map((e) => frameCell(e.frame_idx))].map(csvCell).join(",")
      )
      .join("\n");
  }

  const rows = clean.slice(0, cap).map((e) => {
    if (taskType === "qa") {
      return [e.video_name, frameCell(e.frame_idx), normalizeAnswer(e.answer)].map(csvCell).join(",");
    }
    return [e.video_name, frameCell(e.frame_idx)].map(csvCell).join(","); // kis
  });
  return rows.join("\n");
}

// Tên file gợi ý: <queryId>.csv (sạch ký tự lạ), fallback "submission".
//
// Bỏ đuôi có sẵn trước khi ghép: người dùng rất hay chép nguyên tên file trong
// gói đề vào ô Query ID ("query-p1-15-qa.txt"), mà "query-p1-15-qa.txt.csv" rơi
// đúng vào lỗi BTC liệt kê đầu tiên - nộp sai đuôi file.
export function suggestFilename(queryId, ext = "csv") {
  const base =
    (queryId || "submission").trim().replace(/\.(csv|txt)$/i, "").replace(/[^\w.-]+/g, "_") ||
    "submission";
  return `${base}.${ext}`;
}

// Tên file zip: BTC khuyến cáo chỉ dùng chữ và số.
export function sanitizeZipName(name) {
  const base = String(name || "").trim().replace(/\.zip$/i, "").replace(/[^\w]+/g, "_");
  return `${base || "submission"}.zip`;
}

/**
 * Sinh nội dung nộp cho NHIỀU câu (mỗi câu một file CSV, theo taskType riêng).
 *
 * Câu không xuất được KHÔNG bị bỏ im lặng: nó vẫn có một mục với `error`, để
 * người gọi vừa đóng gói được các câu còn lại vừa nói rõ câu nào hỏng. File rỗng
 * (có đáp án nhưng không mục nào xuất được) cũng tính là hỏng - nhét file 0 byte
 * vào zip chỉ tổ mất một lượt nộp.
 * @param {Array<{qid:number, taskType:string, queryId:string, maxRows:number, numEvents:number, items:Array}>} questions
 * @returns {Array<{qid:number, filename:string, content:string, error:string|null}>}
 */
export function buildExports(questions) {
  const used = new Set();
  return (questions || [])
    .filter((q) => q && Array.isArray(q.items) && q.items.length > 0)
    .map((q) => {
      let filename = suggestFilename(q.queryId || `query-${q.qid}-${q.taskType}`);
      // Hai câu đặt cùng Query ID -> tách tên file để không ghi đè nhau trong zip.
      if (used.has(filename)) filename = suggestFilename(`${q.queryId || "query"}_cau${q.qid}`);
      used.add(filename);

      let content = "";
      let error = null;
      try {
        content = toCSV(q.items, q.taskType, { maxRows: q.maxRows, numEvents: q.numEvents });
        if (!content) error = "không mục nào xuất được ra CSV";
      } catch (e) {
        error = e.message;
      }
      return { qid: q.qid, filename, content, error };
    });
}

/**
 * Đóng gói các file CSV thành .zip ĐÚNG CẤU TRÚC BTC: mọi file nằm trong thư
 * mục "submission/" ở gốc zip (nén thẳng các CSV là một trong 5 lỗi BTC liệt kê).
 * @param {Array<{filename:string, content:string}>} files
 * @returns {Promise<Blob>}
 */
export async function buildSubmissionZip(files) {
  const { default: JSZip } = await import("jszip");
  const zip = new JSZip();
  const folder = zip.folder("submission");
  // Chốt chặn cuối: file rỗng/hỏng không được lọt vào zip dù người gọi sơ ý.
  for (const f of files || []) {
    if (!f || f.error || !f.content) continue;
    folder.file(f.filename, f.content);
  }
  return zip.generateAsync({ type: "blob", compression: "DEFLATE" });
}

// Tải một Blob xuống dưới dạng file trong trình duyệt.
export function downloadBlob(filename, blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// Tải một chuỗi text xuống (xem trước / tải lẻ một câu).
export function downloadText(filename, text, mime = "text/csv;charset=utf-8") {
  downloadBlob(filename, new Blob([text], { type: mime }));
}
