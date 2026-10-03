// src/components/submission/CsvPreviewModal.jsx
// XEM TRƯỚC ĐẦY ĐỦ gói nộp trước khi tải .zip.
//
// Vì sao cần cả một modal cho việc này: BTC chỉ cho 3 lượt nộp mỗi gói và nộp
// sai định dạng VẪN mất một lượt. Phần xem trước cũ trong khay chỉ hiện tên file
// + DÒNG ĐẦU TIÊN của mỗi CSV - đủ để biết file có tồn tại, không đủ để phát
// hiện dòng thứ 7 mang đáp án rỗng hay chuỗi TRAKE thiếu một event.
//
// Hai chế độ xem, và chế độ "dạng bảng" mới là chế độ đáng tin: nó tách cột
// bằng parseCsvLine - đúng luật mà chương trình chấm dùng - nên một đáp án Q&A
// có dấu phẩy hiện ra là 3 cột (đúng) chứ không phải 4 (thứ mắt thường đọc ra
// từ văn bản thô).
import { useEffect, useMemo, useState } from "react";
import {
  MAX_ANSWER_LEN, MAX_ROWS, charLen, downloadText, isValidFrameIdx,
  normalizeAnswer, parseCsvLine, suggestFilename,
} from "../../utils/submissionFormat";
import { copyText } from "../../utils/clipboard";
import { LABEL } from "./tokens";
import { CloseIcon, DownloadIcon, CheckIcon } from "../Icons";

const HEADERS = {
  kis: ["video_name", "frame_idx"],
  qa: ["video_name", "frame_idx", "answer"],
};

/**
 * Soi từng dòng CSV đúng như chương trình chấm sẽ đọc.
 * Trả về [{ cells, problems }] - `problems` là các câu ngắn hiện ngay cạnh dòng.
 */
function inspect(content, q) {
  const lines = String(content || "").split("\n");
  const cap = Math.min(Number(q?.maxRows) || MAX_ROWS, MAX_ROWS);
  const n = Number(q?.numEvents) || 0;
  return lines.map((line, i) => {
    const cells = parseCsvLine(line);
    const problems = [];
    if (i >= cap) problems.push(`vượt trần ${cap} dòng của câu này`);
    if (!cells[0]) problems.push("thiếu video_name");
    if (q?.taskType === "trake") {
      // Một dòng TRAKE = video_name + đúng N frame.
      if (n > 0 && cells.length !== n + 1) {
        problems.push(`${cells.length - 1}/${n} frame - chuỗi này thiếu/thừa event`);
      }
      const idxs = cells.slice(1).map(Number);
      if (idxs.some((v, k) => k > 0 && v <= idxs[k - 1])) {
        problems.push("frame không tăng dần - các event đang sai thứ tự");
      }
    }
    for (let c = 1; c < (q?.taskType === "qa" ? 2 : cells.length); c++) {
      if (!isValidFrameIdx(cells[c])) {
        problems.push(cells[c] == null ? "thiếu cột frame" : `frame "${cells[c]}" không phải số nguyên`);
      }
    }
    if (q?.taskType === "qa") {
      const ans = cells[2];
      if (ans == null || !normalizeAnswer(ans)) problems.push("chưa có câu trả lời");
      else if (charLen(ans) > MAX_ANSWER_LEN) problems.push(`đáp án ${charLen(ans)}/${MAX_ANSWER_LEN} ký tự`);
    }
    return { cells, problems };
  });
}

function CsvPreviewModal({
  open, onClose, exports, questions, current, zipName, answeredCount, blocked, busy, onExportZip,
}) {
  const [selected, setSelected] = useState(current);
  const [table, setTable] = useState(true);
  const [copied, setCopied] = useState(false);

  // Mở ra là đứng sẵn ở câu đang làm; câu đó không có file thì rơi về file đầu.
  useEffect(() => {
    if (!open) return;
    setCopied(false);
    setSelected(exports.some((f) => f.qid === current) ? current : (exports[0]?.qid ?? current));
  }, [open, current, exports]);

  const file = exports.find((f) => f.qid === selected) || null;
  const q = questions.find((x) => x.qid === selected) || null;
  const rows = useMemo(
    () => (file && !file.error ? inspect(file.content, q) : []),
    [file, q]
  );
  const problemCount = rows.filter((r) => r.problems.length).length;
  // Câu có đáp án nhưng KHÔNG có file = câu bị bỏ khỏi zip; nói rõ ở cuối danh sách.
  const emptyQs = questions.filter((x) => !exports.some((f) => f.qid === x.qid));

  // Esc đóng modal này thôi. Bắt ở pha CAPTURE để chạy trước handler toàn cục
  // của SearchPage - không thì một phím Esc đóng luôn cả khay nộp bên dưới.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      onClose();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [open, onClose]);

  if (!open) return null;

  const headers = q ? (HEADERS[q.taskType] || null) : null;

  return (
    // z-[96] tính TRONG <aside> của khay đáp án (cả khay đứng ở z-[70] toàn
    // cục): đủ để phủ khay nộp bài (z-20) đang mở bên dưới, mà vẫn không đua
    // z-index với các modal dựng từ SearchPage.
    <div className="fixed inset-0 z-[96] flex items-center justify-center bg-slate-900/70 p-4" onClick={onClose}>
      <div
        className="flex h-full max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex shrink-0 items-center gap-2 border-b border-slate-200 px-3.5 py-2.5">
          <span className="text-[14.5px] font-bold text-slate-800">Xem trước gói nộp</span>
          <span className="font-mono text-[11.5px] text-slate-400">submission/</span>
          <span className="text-[11.5px] text-slate-400 tabular-nums">
            {exports.filter((f) => !f.error).length} file
          </span>
          <button onClick={onClose} title="Đóng (Esc)" className="ml-auto flex h-7 w-7 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700">
            <CloseIcon className="w-4 h-4" />
          </button>
        </header>

        <div className="flex min-h-0 flex-1">
          {/* Trái: đúng cây file sẽ nằm trong zip */}
          <div className="w-64 shrink-0 overflow-y-auto border-r border-slate-200 bg-slate-50">
            {exports.map((f) => (
              <button
                key={f.qid}
                onClick={() => { setSelected(f.qid); setCopied(false); }}
                className={`flex w-full flex-col items-start gap-0.5 border-b border-slate-200 px-2.5 py-2 text-left transition-colors ${
                  f.qid === selected ? "bg-white ring-1 ring-inset ring-blue-400" : "hover:bg-white"
                }`}
              >
                <div className="flex w-full items-baseline gap-1.5">
                  <span className="shrink-0 text-[10.5px] font-bold text-slate-400 tabular-nums">C{f.qid}</span>
                  <span className={`min-w-0 flex-1 truncate font-mono text-[11px] ${f.error ? "text-red-500 line-through" : "text-slate-700"}`}>
                    {f.filename}
                  </span>
                </div>
                <span className={`text-[10.5px] tabular-nums ${f.error ? "text-red-500" : "text-slate-400"}`}>
                  {f.error ? `bị bỏ - ${f.error}` : `${f.content.split("\n").length} dòng`}
                </span>
              </button>
            ))}
            {emptyQs.length > 0 && (
              <div className="px-2.5 py-2">
                <div className={LABEL}>Không có file trong zip</div>
                <p className="mt-1 text-[10.5px] leading-snug text-slate-400 tabular-nums">
                  {emptyQs.length} câu chưa có đáp án - C{emptyQs.map((x) => x.qid).slice(0, 12).join(", C")}
                  {emptyQs.length > 12 && "…"}
                </p>
              </div>
            )}
          </div>

          {/* Phải: nội dung ĐẦY ĐỦ của file đang chọn */}
          <div className="flex min-w-0 flex-1 flex-col">
            <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-slate-200 px-3 py-2">
              <span className="font-mono text-[11.5px] font-semibold text-slate-700">
                submission/{file?.filename ?? "-"}
              </span>
              {q && (
                <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-slate-500">
                  {q.taskType}{q.taskType === "trake" && q.numEvents ? ` · ${q.numEvents} event` : ""}
                </span>
              )}
              {problemCount > 0 && (
                <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10.5px] font-semibold text-amber-700 tabular-nums">
                  {problemCount} dòng cần xem lại
                </span>
              )}
              <div className="ml-auto flex items-center gap-1">
                {["bảng", "thô"].map((m) => {
                  const isTable = m === "bảng";
                  return (
                    <button
                      key={m}
                      onClick={() => setTable(isTable)}
                      title={
                        isTable
                          ? "Tách cột đúng luật CSV - thấy được số cột mà chương trình chấm đọc ra"
                          : "Đúng từng ký tự sẽ nằm trong file"
                      }
                      className={`rounded-lg px-2 py-1 text-[11px] font-semibold transition-colors ${
                        table === isTable ? "bg-blue-600 text-white" : "text-slate-500 hover:bg-slate-100"
                      }`}
                    >
                      {isTable ? "Dạng bảng" : "Văn bản thô"}
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-auto bg-white">
              {!file ? (
                <p className="p-4 text-[11.5px] text-slate-400">Chưa câu nào có đáp án để xuất.</p>
              ) : file.error ? (
                <p className="m-3 rounded-lg bg-red-50 p-3 text-[11.5px] font-semibold text-red-600 ring-1 ring-red-200">
                  Câu {file.qid} không xuất được: {file.error} - file này sẽ KHÔNG có trong zip.
                </p>
              ) : table ? (
                <table className="w-full border-collapse text-[11.5px]">
                  <thead className="sticky top-0 bg-slate-50 text-left">
                    <tr>
                      <th className="w-10 border-b border-slate-200 px-2 py-1 text-right text-[10px] font-bold uppercase tracking-wider text-slate-400">#</th>
                      {(headers || ["video_name", "frame_1 … frame_N"]).map((h) => (
                        <th key={h} className="border-b border-slate-200 px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                          {h}
                        </th>
                      ))}
                      {/* Cột này luôn có mặt kể cả khi rỗng: thêm/bớt ô theo
                          từng dòng thì các cột trên dưới lệch nhau hết. */}
                      <th className="border-b border-slate-200 px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                        cần xem lại
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r, i) => (
                      <tr key={i} className={r.problems.length ? "bg-amber-50/60" : "odd:bg-slate-50/60"}>
                        <td className="border-b border-slate-100 px-2 py-1 text-right text-[10.5px] text-slate-300 tabular-nums">{i + 1}</td>
                        {/* TRAKE có N+1 cột nên gộp phần frame vào một ô: bảng
                            30 cột không đọc được, mà thứ cần biết chỉ là chuỗi
                            frame có đủ và tăng dần không. */}
                        {headers ? (
                          r.cells.slice(0, headers.length).map((c, k) => (
                            <td key={k} className={`border-b border-slate-100 px-2 py-1 font-mono ${k === 0 ? "font-semibold text-slate-700" : "text-slate-600"} ${k > 0 ? "tabular-nums" : ""}`}>
                              {c === "" ? <span className="text-red-400">(trống)</span> : c}
                            </td>
                          ))
                        ) : (
                          <>
                            <td className="border-b border-slate-100 px-2 py-1 font-mono font-semibold text-slate-700">{r.cells[0]}</td>
                            <td className="border-b border-slate-100 px-2 py-1 font-mono text-slate-600 tabular-nums">
                              {r.cells.slice(1).join(" · ")}
                            </td>
                          </>
                        )}
                        <td className="border-b border-slate-100 px-2 py-1 text-[10.5px] font-semibold text-amber-700">
                          {r.problems.join(" · ")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div className="flex">
                  <div className="shrink-0 select-none border-r border-slate-100 bg-slate-50 px-2 py-2 text-right font-mono text-[11px] text-slate-300 tabular-nums">
                    {file.content.split("\n").map((_, i) => <div key={i}>{i + 1}</div>)}
                  </div>
                  <pre className="flex-1 overflow-x-auto whitespace-pre px-3 py-2 font-mono text-[11.5px] text-slate-700">
                    {file.content}
                  </pre>
                </div>
              )}
            </div>
          </div>
        </div>

        <footer className="flex shrink-0 flex-wrap items-center gap-2 border-t border-slate-200 bg-slate-50 px-3 py-2.5">
          <button
            onClick={async () => setCopied(await copyText(file?.content))}
            disabled={!file || !!file.error}
            className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-[11.5px] font-semibold text-slate-600 transition-colors hover:border-blue-400 hover:text-blue-700 disabled:opacity-40"
          >
            {copied ? "Đã chép" : "Chép nội dung"}
          </button>
          <button
            onClick={() => file && downloadText(file.filename, file.content)}
            disabled={!file || !!file.error}
            className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-[11.5px] font-semibold text-slate-600 transition-colors hover:border-blue-400 hover:text-blue-700 disabled:opacity-40"
          >
            Tải riêng {file ? file.filename : suggestFilename("submission")}
          </button>
          {/* Chốt được ngay tại đây: soát xong mà phải quay ra khay mới bấm tải
              là thêm một bước thừa đúng lúc đang vội. */}
          <button
            onClick={() => onExportZip(false)}
            disabled={answeredCount === 0 || busy || blocked}
            title={blocked ? "Còn lỗi định dạng - sửa hết rồi mới tải được" : `Đóng gói ${answeredCount} câu vào ${zipName}`}
            className="ml-auto inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-3.5 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-emerald-700 disabled:bg-slate-200 disabled:text-slate-400"
          >
            {blocked ? <CloseIcon className="w-4 h-4" /> : busy ? <CheckIcon className="w-4 h-4" /> : <DownloadIcon className="w-4 h-4" />}
            {busy ? "Đang đóng gói…" : `Tải ${zipName} · ${answeredCount} câu`}
          </button>
        </footer>
      </div>
    </div>
  );
}

export default CsvPreviewModal;
