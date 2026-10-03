// src/components/submission/SubmitSheet.jsx
// Khay nộp bài trượt lên từ đáy khay đáp án.
//
// Điểm cốt lõi của bố cục này: khay đè lên DANH SÁCH nhưng KHÔNG che rail câu
// hỏi. Nhờ vậy bấm một dòng lỗi là nhảy thẳng sang câu đó để sửa mà khay vẫn
// mở, rồi đi tiếp lỗi sau - thay vì đóng/mở lại sau mỗi lần sửa.
//
// Khay luôn được mount (chỉ đổi transform/opacity) để cú trượt có chỗ chạy;
// lúc đóng thì `inert` cắt hẳn tương tác và tab-focus.
import { MAX_ATTEMPTS } from "../../hooks/useSubmissionLog";
import { LABEL, CARD, ICON_BTN } from "./tokens";
import { CloseIcon, DownloadIcon, CheckIcon } from "../Icons";

// Một dòng trong bảng kiểm tra trước khi nộp.
function IssueRow({ qid, issues, onJump }) {
  const errs = issues.filter((i) => i.level === "error");
  const warns = issues.filter((i) => i.level === "warn");
  const tone = errs.length ? "text-red-600" : "text-amber-700";
  const dot = errs.length ? "bg-red-500" : "bg-amber-500";

  return (
    <button
      onClick={() => onJump(qid)}
      title={`Nhảy tới câu ${qid} để sửa - khay vẫn mở`}
      className="flex w-full items-start gap-2 border-t border-slate-100 px-2.5 py-2 text-left transition-colors first:border-t-0 hover:bg-slate-50"
    >
      <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} />
      <span className="shrink-0 pt-px text-[10.5px] font-bold text-slate-500 tabular-nums">C{qid}</span>
      <span className={`min-w-0 flex-1 text-[11.5px] leading-snug ${tone}`}>
        {[...errs, ...warns].map((i) => i.msg).join(" · ")}
      </span>
    </button>
  );
}

function SubmitSheet({
  open, onClose, basket, answeredCount, issues, issuesByQ, emptyQids, blocked, errCount,
  exports, onOpenCsv, log, room,
  usedAttempts, zipName, busy, msg, onExportZip, onRedownload, showLog, setShowLog,
}) {
  // "Câu chưa có đáp án" là cảnh báo đúng nhưng KHÔNG hành động được từng cái
  // một, mà đề 30 câu thì nó đẻ ra hàng chục dòng giống hệt nhau chôn mất lỗi
  // thật. Gộp thành một dòng; rail bên trái vốn đã cho biết câu nào còn trống.
  const realIssues = Array.from(issuesByQ.entries())
    .filter(([qid]) => !emptyQids.has(qid))
    .sort((a, b) => a[0] - b[0]);
  const emptyList = Array.from(emptyQids).sort((a, b) => a - b);
  // Cảnh báo đáng đọc = đã trừ nhóm "câu chưa có đáp án" ở trên.
  const realWarnCount = realIssues.reduce(
    (n, [, list]) => n + list.filter((i) => i.level === "warn").length,
    0
  );

  return (
    <div
      inert={!open || undefined}
      onClick={onClose}
      className={`absolute inset-y-0 left-[94px] right-0 z-20 flex items-end transition-opacity duration-200 motion-reduce:transition-none ${
        open ? "opacity-100" : "pointer-events-none opacity-0"
      }`}
    >
      <div className="absolute inset-0 bg-slate-900/30" />
      <aside
        onClick={(e) => e.stopPropagation()}
        className={`relative flex max-h-[84%] w-full flex-col rounded-t-2xl bg-slate-50 shadow-2xl transition-transform duration-200 motion-reduce:transition-none ${
          open ? "translate-y-0" : "translate-y-full"
        }`}
      >
        <header className="shrink-0 rounded-t-2xl border-b border-slate-200 bg-white px-3.5 pb-2 pt-1.5">
          <div className="mx-auto mb-1.5 h-1 w-8 rounded-full bg-slate-300" />
          <div className="flex items-center gap-2">
          <span className="text-[13.5px] font-bold">Nộp bài</span>
          <span className="text-[11.5px] text-slate-400 tabular-nums">
            {answeredCount} câu có đáp án
          </span>
          <button
            onClick={onClose}
            title="Đóng khay nộp bài (Esc)"
            className={`ml-auto ${ICON_BTN}`}
          >
            <CloseIcon className="w-4 h-4" />
          </button>
          </div>
        </header>

        <div className="flex-1 space-y-2.5 overflow-y-auto p-3">
          {/* Trạng thái: nộp sai định dạng vẫn mất 1 trong 3 lượt, nên tình
              trạng lỗi phải là thứ đọc được đầu tiên. */}
          {blocked ? (
            <div className="flex items-center gap-3 rounded-xl bg-red-50 px-3 py-2.5 ring-1 ring-red-200">
              <span className="text-2xl font-bold leading-none text-red-600 tabular-nums">{errCount}</span>
              <span className="text-[13px] font-bold text-red-600">lỗi chặn nộp</span>
              <span className="ml-auto text-right text-[11px] leading-tight text-red-700/80">
                Nộp sai định dạng<br />vẫn mất 1 trong {MAX_ATTEMPTS} lượt
              </span>
            </div>
          ) : (
            answeredCount > 0 && (
              <div className="flex items-center gap-2 rounded-xl bg-emerald-50 px-3 py-2.5 ring-1 ring-emerald-200">
                <CheckIcon className="w-4 h-4 shrink-0 text-emerald-600" />
                <span className="text-[13px] font-bold text-emerald-700">Sẵn sàng nộp</span>
                {realWarnCount > 0 && (
                  <span className="ml-auto text-[11px] text-amber-700 tabular-nums">
                    {realWarnCount} cảnh báo không chặn
                  </span>
                )}
              </div>
            )
          )}

          <div className={`overflow-hidden ${CARD}`}>
            <div className={`border-b border-slate-100 px-2.5 py-1.5 ${LABEL}`}>
              Kiểm tra trước khi nộp
            </div>
            {realIssues.length === 0 ? (
              <p className="px-2.5 py-2 text-[11.5px] text-slate-400">
                {issues.length === 0 ? "Chưa có gì để kiểm tra." : "Các câu đã làm đều sạch lỗi."}
              </p>
            ) : (
              realIssues.map(([qid, list]) => (
                <IssueRow key={qid} qid={qid} issues={list} onJump={basket.setCurrent} />
              ))
            )}
            {emptyList.length > 0 && (
              <p
                title={`Câu ${emptyList.join(", ")}`}
                className="border-t border-slate-100 px-2.5 py-2 text-[11.5px] text-slate-400"
              >
                <span className="font-semibold text-slate-500 tabular-nums">{emptyList.length} câu</span>{" "}
                chưa có đáp án, sẽ không có file trong zip - C{emptyList.slice(0, 8).join(", C")}
                {emptyList.length > 8 && "…"}
              </p>
            )}
          </div>


          {/* Đúng những gì sắp nằm trong zip. Nộp sai mất một lượt, nên đây là
              thứ cuối cùng nên liếc qua trước khi bấm tải. Danh sách dưới đây
              chỉ nói tên file + dòng đầu; bấm tiêu đề để mở màn xem NỘI DUNG
              ĐẦY ĐỦ từng file. */}
          {exports?.length > 0 && (
            <div className={`overflow-hidden ${CARD}`}>
              <button
                onClick={onOpenCsv}
                title="Mở màn xem trước đầy đủ - nội dung từng file CSV, tách cột đúng luật chấm"
                className={`flex w-full items-center gap-1.5 px-2.5 py-1.5 text-left transition-colors hover:bg-slate-50 ${LABEL}`}
              >
                Xem trước CSV · submission/ · {exports.filter((f) => !f.error).length} file
                <span className="ml-auto font-semibold normal-case tracking-normal text-blue-600">Mở →</span>
              </button>
              <ul className="max-h-44 overflow-y-auto border-t border-slate-100">
                {exports.map((f) => {
                  const rows = f.error ? 0 : f.content.split("\n").length;
                  return (
                    <li
                      key={f.qid}
                      className="border-t border-slate-100 px-2.5 py-1.5 first:border-t-0"
                    >
                      <div className="flex items-baseline gap-2">
                        <span className="shrink-0 text-[10.5px] font-bold text-slate-400 tabular-nums">C{f.qid}</span>
                        <span className={`min-w-0 flex-1 truncate font-mono text-[11px] ${f.error ? "text-red-500 line-through" : "text-slate-700"}`}>
                          submission/{f.filename}
                        </span>
                        <span className={`shrink-0 text-[10.5px] tabular-nums ${f.error ? "text-red-500" : "text-slate-400"}`}>
                          {f.error ? "bị bỏ" : `${rows} dòng`}
                        </span>
                      </div>
                      <div className={`mt-0.5 truncate font-mono text-[10.5px] ${f.error ? "text-red-500" : "text-slate-400"}`}>
                        {f.error || f.content.split("\n")[0]}
                      </div>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}

          {/* Nhật ký nộp: bản nào là bản cuối, và tải lại đúng bản đó */}
          {log.entries.length > 0 && (
            <div className="border-t border-slate-200 pt-2">
              <button
                onClick={() => setShowLog((v) => !v)}
                className="text-[11px] text-slate-400 transition-colors hover:text-slate-700"
              >
                {showLog ? "Ẩn" : "Xem"} nhật ký nộp ({log.entries.length})
              </button>
              {showLog && (
                <ul className="mt-1.5 max-h-40 space-y-1 overflow-y-auto">
                  {log.entries.map((e) => (
                    <li
                      key={e.id}
                      className="flex items-center gap-2 rounded-md border border-slate-200 bg-white px-2 py-1"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[11px] font-semibold text-slate-700">{e.zipName}</div>
                        <div className="text-[10px] text-slate-400">
                          {new Date(e.at).toLocaleString("vi-VN")} · {e.files.length} file
                          {e.remote && ` · ${e.member_name || "máy khác"}`}
                        </div>
                      </div>
                      <button
                        onClick={() => onRedownload(e)}
                        disabled={e.remote}
                        title={
                          e.remote
                            ? "Bản này do máy khác tạo - chỉ máy đó tải lại được"
                            : "Tải lại đúng bản zip này"
                        }
                        className="shrink-0 rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-blue-600 disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-slate-400"
                      >
                        <DownloadIcon className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => log.remove(e.id)}
                        disabled={e.remote}
                        title={
                          e.remote
                            ? "Lượt của đồng đội - không xoá từ máy này được"
                            : "Xoá khỏi nhật ký (tải thử chứ chưa nộp thật)"
                        }
                        className="shrink-0 rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-red-600 disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-slate-400"
                      >
                        <CloseIcon className="w-3.5 h-3.5" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>

        {/* Khối nộp ghim ở đáy: danh sách lỗi dài bao nhiêu thì nút tải zip và
            bộ đếm lượt vẫn phải nằm trong tầm mắt. */}
        <footer className="shrink-0 space-y-2 border-t border-slate-200 bg-white p-3">
          {/* Bộ đếm lượt. Không còn ô "Gói" đặt tên tay: mỗi vòng thi là một
              gói và nút "Nhập lại gói đề" đã xoá nhật ký về 0, nên cái tên chỉ
              là một ô phải điền thêm chứ không tách được gì. */}
          <div
            title={
              `BTC cho tối đa ${MAX_ATTEMPTS} lượt nộp mỗi gói, chấm lượt CUỐI CÙNG. ` +
              (room?.active
                ? "Đang đếm cả lượt đồng đội tải trong phòng."
                : "Chỉ đếm lượt đã tải trên máy này.")
            }
            className={`flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-[10.5px] font-bold tabular-nums ${
              usedAttempts >= MAX_ATTEMPTS
                ? "bg-red-50 text-red-600"
                : usedAttempts > 0
                  ? "bg-amber-50 text-amber-700"
                  : "bg-slate-100 text-slate-500"
            }`}
          >
            <span>
              Lượt nộp
              <span className="ml-1 font-normal opacity-70">{room?.active ? "cả phòng" : "máy này"}</span>
            </span>
            <span>{usedAttempts}/{MAX_ATTEMPTS}</span>
          </div>

          <button
            onClick={() => onExportZip(false)}
            disabled={answeredCount === 0 || busy || blocked}
            title={
              blocked
                ? "Còn lỗi định dạng - sửa hết rồi mới tải được"
                : `Đóng gói ${answeredCount} câu vào ${zipName} (thư mục submission/ bên trong)`
            }
            className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-600 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-emerald-700 disabled:bg-slate-200 disabled:text-slate-400"
          >
            <DownloadIcon className="w-4 h-4" />
            {busy ? "Đang đóng gói…" : `Tải ${zipName} · ${answeredCount} câu`}
          </button>

          {blocked && answeredCount > 0 && (
            <button
              onClick={() => onExportZip(true)}
              title="Câu TRAKE chưa khai số event vẫn KHÔNG xuất được - không biết cắt chuỗi ở đâu thì mọi frame thành một dòng riêng"
              className="w-full text-center text-[11px] text-slate-400 underline transition-colors hover:text-red-600"
            >
              Vẫn tải xuống dù còn {errCount} lỗi
            </button>
          )}

          {msg && <div className="break-words text-xs text-slate-600">{msg}</div>}
        </footer>
      </aside>
    </div>
  );
}

export default SubmitSheet;
