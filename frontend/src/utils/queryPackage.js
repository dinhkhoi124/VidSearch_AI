// src/utils/queryPackage.js
// Đọc gói truy vấn BTC phát theo đợt. Tới tay theo hai kiểu:
//   * MỘT file .zip chứa cả bộ đề (kiểu thường gặp - xem contest/*.zip);
//   * hoặc các file .txt rời, đặt tên theo quy ước
//       query-<số>-<task>.txt        (query-1-kis.txt)
//       query-<đợt>-<số>-<task>.txt  (query-p1-15-qa.txt)
//
// Từ tên file suy ra được CẢ BA thứ mà trước đây phải gõ tay cho từng câu: số
// câu của đề, loại task, và tên file CSV phải nộp lại (đúng bằng tên truy vấn).
// Nội dung file là đề bài -> đọc luôn trong app, khỏi alt-tab.
import { parseQueryId } from "./submissionFormat.js";

/**
 * Phân tích MỘT tên file.
 * `queryId` GIỮ NGUYÊN tên gốc (kể cả tiền tố đợt): file nộp phải trùng tên truy
 * vấn BTC phát thì mới được chấm.
 * @returns {{qid:number, taskType:string, queryId:string} | null}
 */
export function parseQueryFilename(filename) {
  const base = String(filename || "")
    .replace(/^.*[\\/]/, "")   // bỏ đường dẫn nếu trình duyệt/zip trả về
    .replace(/\.txt$/i, "")
    .trim();
  const parsed = parseQueryId(base);
  return parsed ? { qid: parsed.qid, taskType: parsed.taskType, queryId: base } : null;
}

// Một event của đề TRAKE. Hai lối viết đều gặp trong đề thật:
//   "E1: Khoảnh khắc..."   (gói THUNGHIEM 2026)
//   "1. Vận động viên..."  / "1) ..."
const EVENT_LINE_RES = [
  /^\s*E\s*(\d{1,2})\s*[:.)-]\s*\S/i,
  /^\s*(\d{1,2})\s*[.)]\s*\S/,
];

/**
 * Đoán số event của câu TRAKE từ nội dung đề. Chỉ là GỢI Ý để prefill - người
 * dùng vẫn phải xác nhận, vì đoán sai thì cả file nộp sai số cột.
 * @returns {number|null}
 */
export function guessNumEvents(text) {
  const lines = String(text || "").split(/\r?\n/);
  // Thử từng lối viết riêng: trộn cả hai vào một danh sách thì một dòng "E1:"
  // và một dòng "1." trong cùng đề sẽ đếm thành hai event.
  for (const re of EVENT_LINE_RES) {
    const nums = [];
    for (const line of lines) {
      const m = line.match(re);
      if (m) nums.push(parseInt(m[1], 10));
    }
    // Chỉ tin khi các số chạy liên tục 1..n - tránh bắt nhầm số liệu trong câu văn.
    if (nums.length >= 2 && nums.every((v, i) => v === i + 1)) return nums.length;
  }
  return null;
}

// Bung một file .zip thành danh sách {name, text}. jszip nạp động y như lúc đóng
// gói bài nộp (xem submissionFormat.buildSubmissionZip) - thư viện chỉ tải về khi
// thật sự có người nhập gói đề.
async function readZip(file) {
  const { default: JSZip } = await import("jszip");
  const zip = await JSZip.loadAsync(file);
  const out = [];
  for (const entry of Object.values(zip.files)) {
    // __MACOSX/ là rác zip của macOS: bên trong có "._query-1-kis.txt" trùng tên
    // với file thật, để lọt vào là đè đề bằng vài byte metadata.
    if (entry.dir || /(^|\/)__MACOSX\//.test(entry.name)) continue;
    if (!/\.txt$/i.test(entry.name)) continue;
    out.push({ name: entry.name, text: await entry.async("string") });
  }
  return out;
}

/**
 * Đọc danh sách File (từ input/drag-drop) thành cấu hình các câu.
 * Nhận cả .zip lẫn .txt rời, trộn lẫn cũng được.
 * @param {File[]} files
 * @returns {Promise<{questions: Array, skipped: string[], fromZip: boolean, missing: number[]}>}
 */
export async function readQueryPackage(files) {
  const skipped = [];
  let fromZip = false;

  // Bung zip trước để phần sau chỉ còn phải làm việc với (tên, nội dung).
  const entries = [];
  for (const file of Array.from(files || [])) {
    if (/\.zip$/i.test(file.name)) {
      fromZip = true;
      try {
        entries.push(...(await readZip(file)));
      } catch {
        skipped.push(`${file.name} (không đọc được file zip)`);
      }
      continue;
    }
    try {
      entries.push({ name: file.name, text: await file.text() });
    } catch {
      entries.push({ name: file.name, text: "" });
    }
  }

  // Trùng số câu -> giữ bản ĐỌC SAU (BTC phát bù thường là bản sửa), nhưng vẫn
  // phải nói ra: im lặng bỏ một file đề là mất hẳn một câu.
  const byQid = new Map();
  for (const { name, text } of entries) {
    const parsed = parseQueryFilename(name);
    if (!parsed) {
      skipped.push(name);
      continue;
    }
    const prev = byQid.get(parsed.qid);
    if (prev) skipped.push(`${prev.queryId}.txt (trùng câu ${parsed.qid})`);
    byQid.set(parsed.qid, {
      ...parsed,
      queryText: text.trim(),
      numEvents: parsed.taskType === "trake" ? guessNumEvents(text) : null,
    });
  }

  const questions = Array.from(byQid.values()).sort((a, b) => a.qid - b.qid);
  // Số câu khuyết giữa 1..max: gói thật có thể vốn không có câu 3. Báo ra để
  // người dùng biết đó là gói thiếu chứ không phải app đọc sót một file.
  const missing = [];
  if (questions.length) {
    for (let qid = 1; qid < questions[questions.length - 1].qid; qid += 1) {
      if (!byQid.has(qid)) missing.push(qid);
    }
  }

  return { questions, skipped, fromZip, missing };
}
