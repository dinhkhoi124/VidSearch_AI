// src/components/QueryPackageImport.jsx
// Nhận gói đề BTC phát -> tự dựng cấu hình các câu. Thay cho việc gõ tay "Số
// câu" rồi chọn tay task cho từng câu (dễ sai, mà sai task là sai luôn tên file
// nộp).
//
// Nhận CẢ HAI dạng gói vì BTC phát theo cả hai:
//   * một file .zip chứa trọn bộ đề (dạng thường gặp - xem contest/*.zip);
//   * các file query-*.txt rời (phát bù, sửa đề giữa vòng).
//
// Hai chế độ nạp, vì gói đề tới tay theo hai kiểu rất khác nhau:
//   * GỘP - BTC phát bù một file hoặc sửa đề giữa vòng: chỉ ghi đè cấu hình,
//     đáp án đã tìm giữ nguyên.
//   * TỪ ĐẦU - gói của một VÒNG KHÁC: phải xoá sạch đề cũ, nếu không câu thừa
//     của vòng trước vẫn nằm trong state (kể cả câu đã bị ẩn vì ngoài phạm vi
//     "Số câu") và sẽ lẫn vào zip nộp của vòng này.
// Một file .zip gần như luôn là trọn gói một vòng -> mặc định chọn TỪ ĐẦU cho
// nó, còn .txt rời thì mặc định GỘP. Người dùng bấm đổi thì tôn trọng lựa chọn.
import { useMemo, useRef, useState } from "react";
import { readQueryPackage } from "../utils/queryPackage";
import { TASK_SHORT } from "../utils/submissionFormat";
import ConfirmAction from "./submission/ConfirmAction";
import { UploadIcon } from "./Icons";

// `big`: bản dùng ở màn hình thiết lập đầu vòng - lúc đó nhập đề là việc DUY
// NHẤT đáng làm nên ô kéo-thả được phóng to, khác với lúc gọi lại từ popover ⚙.
function QueryPackageImport({ basket, onImported, big = false }) {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);
  const [report, setReport] = useState(null);
  const [reset, setReset] = useState(false);
  // Người dùng đã tự bấm chọn chế độ chưa - nếu rồi thì thả .zip cũng không tự
  // đổi sang "từ đầu" nữa: đang cố ý gộp mà bị chuyển sang xoá sạch là mất bài.
  const [modeTouched, setModeTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  // Gói đã đọc xong nhưng còn chờ xác nhận (xem ConfirmAction bên dưới).
  const [pending, setPending] = useState(null);

  // Đếm trên `questions` chứ không dùng basket.totalCount: totalCount chỉ cộng
  // các câu 1..N, mà thứ "nhập lại từ đầu" xoá đi lại gồm cả câu ngoài phạm vi.
  const old = useMemo(() => {
    const qids = Object.keys(basket.questions).map(Number);
    const answered = qids.filter((q) => basket.questions[q].items.length > 0);
    return {
      // Có đề cũ để mà xoá hay không: đủ để quyết định có hiện lựa chọn chế độ.
      any: qids.length > 0 || basket.numQuestions > 1,
      questions: Math.max(basket.numQuestions, ...qids, 0),
      answered: answered.length,
      frames: answered.reduce((s, q) => s + basket.questions[q].items.length, 0),
    };
  }, [basket.questions, basket.numQuestions]);

  const apply = (pkg) => {
    basket.importPackage(pkg.questions, { reset: pkg.reset });
    setReport({ error: false, ...pkg });
    setPending(null);
    // Xoá xong thì về lại chế độ gộp: gói đề hay tới làm hai đợt (chọn thiếu
    // file rồi thả thêm), mà đợt hai với cờ reset còn bật sẽ xoá luôn đợt một.
    setReset(false);
    setModeTouched(false);
    onImported?.(pkg.questions);
  };

  const handleFiles = async (fileList) => {
    setBusy(true);
    setPending(null);
    try {
      const { questions, skipped, fromZip, missing } = await readQueryPackage(fileList);
      if (!questions.length) {
        setReport({
          error: true,
          skipped,
          msg: fromZip
            ? "File zip không chứa file nào đúng mẫu query-<số>-<task>.txt"
            : "Không có file nào đúng mẫu query-<số>-<task>.txt",
        });
        return;
      }
      // Thả .zip = trọn gói một vòng -> mặc định dựng lại từ đầu. Đổi luôn ô
      // chọn chế độ để người dùng thấy chuyện đó trước khi bấm xác nhận.
      const useReset = modeTouched ? reset : fromZip;
      if (useReset !== reset) setReset(useReset);

      const pkg = { questions, skipped, fromZip, missing, reset: useReset };
      // Nhập sẽ ghi đè cấu hình câu -> hỏi trước nếu đang có đề, vì đổi task của
      // một câu đã tìm xong là chuyện đáng để dừng lại một nhịp. Chế độ từ đầu
      // còn XOÁ đáp án nên phải nói thẳng mất bao nhiêu, kể cả khi giỏ đang rỗng.
      if (useReset ? old.any : basket.totalCount > 0) {
        setPending(pkg);
        setReport(null);
        return;
      }
      apply(pkg);
    } finally {
      setBusy(false);
    }
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    handleFiles(e.dataTransfer.files);
  };

  const pickMode = (value) => { setReset(value); setModeTouched(true); };

  return (
    <div>
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") inputRef.current?.click(); }}
        title="Kéo-thả file .zip gói đề BTC, hoặc các file query-*.txt rời"
        className={`flex cursor-pointer items-center justify-center gap-2 rounded-lg border border-dashed transition-colors ${
          big ? "flex-col px-4 py-8 text-sm" : "px-3 py-2.5 text-xs"
        } ${
          dragging
            ? reset
              ? "border-red-500 bg-red-50 text-red-700"
              : "border-blue-500 bg-blue-50 text-blue-700"
            : "border-slate-300 bg-white text-slate-500 hover:border-blue-400 hover:text-blue-600"
        }`}
      >
        <UploadIcon className={`shrink-0 ${big ? "w-7 h-7" : "w-4 h-4"}`} />
        <span>
          {busy ? (
            "Đang đọc gói đề…"
          ) : (
            <>
              Kéo-thả <span className="font-semibold">file .zip</span> gói đề BTC vào đây
            </>
          )}
        </span>
        {big && !busy && (
          <span className="text-[11px] text-slate-400">
            hoặc bấm để chọn file · nhận cả các file query-*.txt rời
          </span>
        )}
      </div>
      <input
        ref={inputRef}
        type="file"
        accept=".zip,.txt,application/zip,text/plain"
        multiple
        className="hidden"
        onChange={(e) => { handleFiles(e.target.files); e.target.value = ""; }}
      />

      {/* Chưa có đề nào thì hai chế độ cho ra kết quả y hệt nhau -> không hỏi. */}
      {old.any && (
        <div className="mt-2 space-y-1">
          <ModeOption
            active={!reset}
            onClick={() => pickMode(false)}
            label="Gộp vào đề hiện tại"
            hint="Ghi đè cấu hình các câu trong gói, giữ nguyên đáp án đã tìm."
          />
          <ModeOption
            active={reset}
            danger
            onClick={() => pickMode(true)}
            label="Nhập lại từ đầu"
            hint={`Vòng thi mới: xoá ${old.questions} câu cũ${
              old.frames ? ` và ${old.frames} đáp án` : ""
            }, dựng lại đúng theo gói.`}
          />
        </div>
      )}

      {pending && (
        <div className="mt-2">
          <ConfirmAction
            title={
              pending.reset
                ? `Nhập lại từ đầu ${pending.questions.length} câu, xoá hết đề hiện tại?`
                : `Nhập ${pending.questions.length} câu từ gói đề?`
            }
            detail={
              pending.reset
                ? `Toàn bộ đề hiện tại (${old.questions} câu` +
                  (old.frames ? `, ${old.frames} đáp án ở ${old.answered} câu` : ", chưa có đáp án nào") +
                  ") sẽ bị xoá và dựng lại theo gói mới. Không hoàn tác được, cả phòng cùng bị xoá. " +
                  "Nhật ký nộp và lịch sử tìm kiếm vẫn được giữ."
                : "Cấu hình (loại task, Query ID, số event, đề bài) của các câu này sẽ bị ghi đè. " +
                  "Đáp án đã có trong giỏ được giữ nguyên."
            }
            confirmLabel={pending.reset ? "Xoá & nhập lại" : "Nhập đè"}
            onCancel={() => setPending(null)}
            onConfirm={() => apply(pending)}
          />
        </div>
      )}

      {report && (
        <div className="mt-2 space-y-1 text-[11px]">
          {report.error ? (
            <p className="text-red-600">{report.msg}</p>
          ) : (
            <p className="text-emerald-600">
              {report.reset ? "Đã nhập lại từ đầu" : "Đã nhập"} {report.questions.length} câu:{" "}
              {report.questions
                .map((q) => `${q.qid}·${TASK_SHORT[q.taskType]}${q.numEvents ? `(${q.numEvents}ev)` : ""}`)
                .join(", ")}
            </p>
          )}
          {report.missing?.length > 0 && (
            <p className="text-slate-400">
              Gói không có câu {report.missing.join(", ")} - các câu này để trống, đừng nộp file cho chúng.
            </p>
          )}
          {report.skipped?.length > 0 && (
            <p className="text-amber-600">
              Bỏ qua {report.skipped.length} file sai mẫu tên: {report.skipped.join(", ")}
            </p>
          )}
          {!report.error && report.questions.some((q) => q.taskType === "trake" && !q.numEvents) && (
            <p className="text-amber-600">
              Câu TRAKE chưa đoán được số event - phải tự khai ở nút “Sửa”, nếu không không đóng gói được.
            </p>
          )}
          {!report.error && report.questions.some((q) => q.numEvents) && (
            <p className="text-slate-400">
              Câu TRAKE: kiểm tra lại ô “Event” - số event đoán từ đề chỉ là gợi ý.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// Class VIẾT ĐỦ chứ không ghép chuỗi `border-${accent}-300`: Tailwind quét mã
// nguồn theo văn bản, tên class dựng lúc chạy sẽ không có trong bundle và nút
// hiện ra không màu.
const MODE_SKIN = {
  blue: { box: "border-blue-300 bg-blue-50/60", dot: "border-blue-500", fill: "bg-blue-500", text: "text-blue-700" },
  red: { box: "border-red-300 bg-red-50/60", dot: "border-red-500", fill: "bg-red-500", text: "text-red-700" },
};

// Một lựa chọn chế độ. Cả khối bấm được (không chỉ cái chấm) vì hai dòng chữ
// mới là thứ người dùng đọc để chọn.
function ModeOption({ active, danger, onClick, label, hint }) {
  const skin = MODE_SKIN[danger ? "red" : "blue"];
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`flex w-full items-start gap-2 rounded-lg border px-2.5 py-1.5 text-left transition-colors ${
        active ? skin.box : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"
      }`}
    >
      <span
        className={`mt-[3px] flex h-3 w-3 shrink-0 items-center justify-center rounded-full border ${
          active ? skin.dot : "border-slate-300"
        }`}
      >
        {active && <span className={`h-1.5 w-1.5 rounded-full ${skin.fill}`} />}
      </span>
      <span className="min-w-0">
        <span className={`block text-[11.5px] font-semibold ${active ? skin.text : "text-slate-600"}`}>
          {label}
        </span>
        <span className="block text-[10.5px] leading-snug text-slate-400">{hint}</span>
      </span>
    </button>
  );
}

export default QueryPackageImport;
