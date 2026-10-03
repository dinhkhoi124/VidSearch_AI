// src/components/SubmissionPanel.jsx
// Drawer bên phải: quản lý GIỎ ĐÁP ÁN CỦA TỪNG CÂU (xếp hạng) và đóng gói file
// nộp theo SPEC BTC AIC 2026 - một file .zip chứa thư mục submission/.
//
// Bố cục: rail câu hỏi dựng ĐỨNG bên trái (luôn thấy, không tốn chiều cao) +
// một cột nội dung header → đề bài → danh sách đáp án (vùng cuộn duy nhất) →
// footer. Khối nộp bài là KHAY trượt lên từ đáy, đè lên danh sách nhưng không
// che rail - nên sửa lỗi trước khi nộp không phải đóng/mở khay sau mỗi câu.
//
// File này giữ toàn bộ phần TÍNH TOÁN (gom câu, kiểm tra, đóng gói); phần vẽ
// chia sang components/submission/.
import { useEffect, useMemo, useState } from "react";
import {
  downloadBlob, buildExports, buildSubmissionZip, sanitizeZipName, chunkTrake,
} from "../utils/submissionFormat";
import { verifyAnswers } from "../api/searchService";
import CsvPreviewModal from "./submission/CsvPreviewModal";
import { validateSubmission, groupIssues, hasErrors } from "../utils/submissionValidate";
import { useSubmissionLog } from "../hooks/useSubmissionLog";
import { usePersistedState } from "../hooks/usePersistedState";
import QuestionRail from "./submission/QuestionRail";
import PanelHeader from "./submission/PanelHeader";
import AnswerList from "./submission/AnswerList";
import SubmitSheet from "./submission/SubmitSheet";
import SetupScreen from "./submission/SetupScreen";
import { RefreshIcon, UploadIcon } from "./Icons";

// `sheetOpen` do SearchPage giữ, không phải state cục bộ: phím Esc phải đóng
// KHAY trước rồi mới đến drawer, mà thứ tự đó nằm ở closeTopOverlay bên đó.
function SubmissionPanel({
  isOpen, onClose, basket, onFeedback, feedbackLoading, onVideoClick, onFramesClick, onPickFrame,
  room, sheetOpen, setSheetOpen, csvOpen, setCsvOpen,
}) {
  const {
    current, items, count, taskType, queryId, numEvents,
    questionList, itemsOf, numQuestions, totalCount,
  } = basket;

  const log = useSubmissionLog(room);
  // Đã qua bước nhập đề chưa - nhớ theo máy, để lần mở sau không hỏi lại.
  const [setupDone, setSetupDone] = usePersistedState("aic.setupdone", false);
  // Gọi lại màn nhập đề GIỮA VÒNG (nút "Nhập lại gói đề" ở ⚙). Phải là cờ
  // riêng: needsSetup bên dưới chỉ tự bật khi phòng còn trắng, nên hạ setupDone
  // lúc đã có đề thì không mở ra được gì - đúng lúc cần nó nhất là lúc sang
  // vòng mới. Không persist: đây là một hành động, không phải trạng thái.
  const [reopenSetup, setReopenSetup] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  // Kiểm chứng bằng chứng phía server (/verify_answers): đối chiếu giỏ đáp án
  // với ASR/OCR/caption trong index - bắt kiểu lỗi "nộp nhầm video nhìn giống".
  const [verify, setVerify] = useState({ busy: false, reports: null, error: "" });
  // Đổi câu là báo cáo cũ hết ngữ cảnh - xoá đi, không để kết quả câu 5 nằm
  // dưới giỏ câu 6.
  useEffect(() => {
    setVerify({ busy: false, reports: null, error: "" });
  }, [current]);
  const [showLog, setShowLog] = useState(false);
  // HAI popover riêng, không dùng chung một cờ: ⚙ là phạm vi CẢ BỘ ĐỀ, "Sửa" là
  // phạm vi MỘT CÂU. Trước đây chung một `configOpen` nên hai nút mở ra đúng một
  // tấm trộn lẫn hai phạm vi, và "Sửa" ở dải dưới lại bật panel neo tận góc trên.
  const [deckOpen, setDeckOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);

  // Gom dữ liệu tất cả các câu để kiểm tra + đóng gói cả đề.
  const allQuestions = useMemo(
    () => questionList.map((q) => ({ ...q, items: itemsOf(q.qid) })),
    [questionList, itemsOf]
  );
  const answeredCount = useMemo(
    () => allQuestions.filter((q) => q.items.length > 0).length,
    [allQuestions]
  );
  // Câu rỗng sinh đúng một cảnh báo giống hệt nhau; khay nộp bài gộp chúng lại
  // thay vì kê thành hàng chục dòng che mất lỗi thật.
  const emptyQids = useMemo(
    () => new Set(allQuestions.filter((q) => q.items.length === 0).map((q) => q.qid)),
    [allQuestions]
  );

  const issues = useMemo(() => validateSubmission(allQuestions), [allQuestions]);
  const issuesByQ = useMemo(() => groupIssues(issues), [issues]);
  const blocked = hasErrors(issues);
  const errCount = issues.filter((i) => i.level === "error").length;

  // Đúng những gì sắp nằm trong zip - dùng cho cả xem trước lẫn lúc đóng gói.
  const exports = useMemo(() => buildExports(allQuestions), [allQuestions]);

  // TRAKE: chia giỏ thành các ứng viên để vẽ vách ngăn "Đáp án #k".
  const trakeGroups = useMemo(
    () => (taskType === "trake" && numEvents ? chunkTrake(items, numEvents) : null),
    [taskType, numEvents, items]
  );
  // id -> {cand, event} để gắn nhãn cho từng dòng mà không phải tính lại trong vòng lặp.
  const trakeLabel = useMemo(() => {
    const m = new Map();
    if (!trakeGroups) return m;
    trakeGroups.forEach((g, gi) =>
      g.forEach((it, ei) => m.set(it.id, { cand: gi + 1, event: ei + 1, first: ei === 0 }))
    );
    return m;
  }, [trakeGroups]);

  // Không còn tên gói đặt tay: cả vòng thi dồn vào một khoá đếm duy nhất, và
  // sang vòng mới thì handleResetDeck xoá sạch nhật ký nên bộ đếm vẫn về 0
  // đúng lúc. Zip vì thế luôn là submission.zip - BTC không soi tên file.
  const usedAttempts = log.countFor("");
  const zipName = sanitizeZipName("submission");
  // Chưa có đề mà cũng chưa có đáp án nào -> việc duy nhất đáng làm là nhập đề.
  const needsSetup = reopenSetup || (numQuestions <= 1 && totalCount === 0 && !setupDone);
  const closeSetup = () => { setSetupDone(true); setReopenSetup(false); };
  // Có ít nhất một câu mang đề bài -> đề này đến từ gói BTC, nên câu KHÔNG có đề
  // là chuyện đáng nói (xem PanelHeader).
  const hasPackage = useMemo(() => questionList.some((q) => q.queryText), [questionList]);

  if (!isOpen) return null;

  /**
   * Sang VÒNG THI MỚI: xoá sạch đề hiện tại rồi quay về màn nhập gói đề.
   *
   * Phải xoá cả `questions` chứ không chỉ hạ numQuestions - câu ngoài phạm vi
   * vẫn nằm nguyên trong state (xem hiddenWithData) và sẽ sống lại kèm đáp án
   * vòng trước ngay khi vòng sau có nhiều câu hơn.
   *
   * Nhật ký nộp xoá luôn: BTC đếm 3 lượt THEO GÓI, vòng mới là gói mới nên bộ
   * đếm phải về 0; để lại lượt của vòng cũ thì thanh "Lượt 2/3" nói dối.
   */
  const handleResetDeck = () => {
    basket.clearAll();
    basket.setNumQuestions(1);
    log.clearAll();
    setMsg("");
    // Hạ cờ này là đủ để needsSetup bật lại (numQuestions và totalCount vừa về
    // mức đầu vòng) -> hiện màn "Bắt đầu một vòng thi", không phải màn "nhập lại".
    setSetupDone(false);
    setReopenSetup(false);
  };

  const handleExportZip = async (force = false) => {
    if (blocked && !force) return;
    setBusy(true);
    setMsg("");
    try {
      if (!exports.length) {
        setMsg("Chưa câu nào có đáp án.");
        return;
      }
      // Câu hỏng thì đóng gói các câu còn lại chứ không huỷ cả lượt - nhưng phải
      // nói rõ câu nào bị bỏ, vì thiếu file là câu đó coi như bỏ trắng.
      const files = exports.filter((f) => !f.error);
      const failed = exports.filter((f) => f.error);
      if (!files.length) {
        setMsg(`Không câu nào xuất được: ${failed.map((f) => `C${f.qid} (${f.error})`).join(" · ")}`);
        return;
      }
      const blob = await buildSubmissionZip(files);
      downloadBlob(zipName, blob);
      log.record({ packageName: "", zipName, files });
      setMsg(
        `Đã tạo ${zipName} - ${files.length} file trong thư mục submission/` +
        (failed.length ? ` · BỎ QUA ${failed.map((f) => `C${f.qid} (${f.error})`).join(", ")}` : "")
      );
    } catch (e) {
      setMsg(`Lỗi đóng gói: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  /**
   * Gửi MỘT câu (câu đang chọn) lên /verify_answers - kiểm cả đề 30 câu một
   * lượt vừa tốn tài nguyên server vừa đẻ ra danh sách dài không ai đọc; luồng
   * thật là làm xong câu nào kiểm câu đó. Chỉ câu CÓ đề bài mới kiểm được -
   * anchor trích từ chính câu chữ của đề. TRAKE gửi theo ứng viên (mỗi nhóm
   * numEvents frame là một dòng) cho khớp cấu trúc file nộp.
   */
  const handleVerify = async () => {
    setVerify({ busy: true, reports: null, error: "" });
    try {
      const q = allQuestions.find((x) => x.qid === current);
      if (!q || !q.items.length) {
        setVerify({ busy: false, reports: null, error: `Câu ${current} chưa có đáp án trong giỏ.` });
        return;
      }
      if (!q.queryText) {
        setVerify({ busy: false, reports: null, error: `Câu ${current} chưa có đề bài - không có gì để đối chiếu.` });
        return;
      }
      const question = {
        qid: q.qid,
        task_type: q.taskType,
        query_text: q.queryText,
        rows:
          q.taskType === "trake" && q.numEvents
            ? chunkTrake(q.items, q.numEvents).map((g) => ({
                video_name: g[0]?.video_name || "",
                frames: g.map((it) => it.frame_idx).filter((n) => n != null),
                answer: "",
              }))
            : q.items.map((it) => ({
                video_name: it.video_name,
                frames: it.frame_idx != null ? [it.frame_idx] : [],
                answer: it.answer || "",
              })),
      };
      const data = await verifyAnswers([question]);
      setVerify({ busy: false, reports: data.reports || [], error: "" });
    } catch (e) {
      setVerify({ busy: false, reports: null, error: `Lỗi kiểm chứng: ${e.message}` });
    }
  };

  // Mục do máy khác tạo chỉ đồng bộ metadata (xem useSubmissionLog) -> không có
  // nội dung CSV để dựng lại zip.
  const handleRedownload = async (entry) => {
    if (!entry.files?.some((f) => f.content)) {
      setMsg("Bản này do máy khác tạo - chỉ máy đó tải lại được đúng file zip.");
      return;
    }
    const blob = await buildSubmissionZip(entry.files);
    downloadBlob(entry.zipName, blob);
  };

  return (
    <div className="fixed inset-0 z-[70] flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-slate-900/30 backdrop-blur-[1px]" />
      <aside
        className="relative flex h-full w-[36rem] max-w-full border-l border-slate-200 bg-slate-50 text-slate-800 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {needsSetup ? (
          <div className="flex min-w-0 flex-1 flex-col">
            <PanelHeader
              basket={basket}
              onClose={onClose}
              onReopenSetup={() => setReopenSetup(true)}
              onResetDeck={handleResetDeck}
              answeredCount={answeredCount}
              attempts={usedAttempts}
              roomActive={room?.active}
              deckOpen={deckOpen}
              setDeckOpen={setDeckOpen}
              editOpen={editOpen}
              setEditOpen={setEditOpen}
              minimal
            />
            <SetupScreen basket={basket} onDone={closeSetup} reopened={reopenSetup} />
          </div>
        ) : (
          <>
            <QuestionRail
              basket={basket}
              onOpenDeck={() => setDeckOpen(true)}
            />

            <div className="flex min-w-0 flex-1 flex-col">
              <PanelHeader
                basket={basket}
                onClose={onClose}
                onReopenSetup={() => setReopenSetup(true)}
                onResetDeck={handleResetDeck}
                answeredCount={answeredCount}
                attempts={usedAttempts}
                roomActive={room?.active}
                deckOpen={deckOpen}
                setDeckOpen={setDeckOpen}
                editOpen={editOpen}
                setEditOpen={setEditOpen}
                hasPackage={hasPackage}
              />

              <AnswerList
                basket={basket}
                items={items}
                count={count}
                current={current}
                taskType={taskType}
                numEvents={numEvents}
                trakeLabel={trakeLabel}
                onVideoClick={onVideoClick}
                onFramesClick={onFramesClick}
                onPickFrame={onPickFrame}
                room={room}
              />

              {/* "Tìm tương tự" tác động lên MỘT câu, "Nộp bài" đóng gói CẢ ĐỀ.
                  Xếp chồng chứ không cạnh nhau: đứng cạnh một nút của-câu-này thì
                  nút nộp bài đọc ra như thể chỉ nộp câu đang mở, mà nó lại là thao
                  tác tốn một trong ba lượt của cả nhóm. Kéo hết bề ngang + ghi rõ
                  số câu sắp gói là chỗ duy nhất nói được điều đó. */}
              <footer className="shrink-0 space-y-2 border-t border-slate-200 bg-white p-3">
                {/* Kiểm chứng bằng chứng CHO CÂU ĐANG CHỌN: server đối chiếu
                    từng (video, frame) với ASR/OCR/caption - bắt kiểu "nộp nhầm
                    video nhìn giống" mà kiểm tra định dạng không thấy được.
                    Từng câu chứ không cả đề: làm xong câu nào kiểm câu đó,
                    kiểm 30 câu một lượt vừa tốn tài nguyên vừa không ai đọc.
                    ĐỎ = dừng lại nhìn, không phải chắc chắn sai (whisper nghe
                    nhầm tên riêng vẫn tạo cảnh báo oan). */}
                {count > 0 && (
                  <div className="space-y-1">
                    <button
                      onClick={handleVerify}
                      disabled={verify.busy}
                      title="Đối chiếu đáp án câu này với lời nói / chữ trên hình / caption của video"
                      className="inline-flex w-full items-center justify-center gap-1.5 rounded-xl border border-slate-300 bg-white py-1.5 text-[11.5px] font-semibold text-slate-600 transition-colors hover:border-amber-300 hover:text-amber-700 disabled:text-slate-400"
                    >
                      <RefreshIcon className={`w-4 h-4 ${verify.busy ? "animate-spin" : ""}`} />
                      {verify.busy ? "Đang đối chiếu…" : `Kiểm chứng câu ${current} · ${count} frame`}
                    </button>
                    {verify.error && (
                      <p className="rounded-lg bg-red-50 px-2.5 py-1.5 text-[11px] leading-snug text-red-600 ring-1 ring-red-100">
                        {verify.error}
                      </p>
                    )}
                    {verify.reports && (
                      verify.reports.some((r) => r.warnings.length) ? (
                        <ul className="max-h-32 space-y-1 overflow-y-auto">
                          {verify.reports.flatMap((r) =>
                            r.warnings.map((w, i) => (
                              <li
                                key={`${r.qid}-${i}`}
                                className={`rounded-lg px-2.5 py-1.5 text-[11px] leading-snug ring-1 ${
                                  w.level === "red"
                                    ? "bg-red-50 text-red-600 ring-red-100"
                                    : "bg-amber-50 text-amber-700 ring-amber-100"
                                }`}
                              >
                                {w.msg}
                              </li>
                            ))
                          )}
                        </ul>
                      ) : (
                        <p className="rounded-lg bg-emerald-50 px-2.5 py-1.5 text-[11px] leading-snug text-emerald-700 ring-1 ring-emerald-100">
                          Không thấy mâu thuẫn với bằng chứng trong video.
                        </p>
                      )
                    )}
                  </div>
                )}
                {/* Phụ = viền xám trung tính, chính = xanh dương đặc. Trước đây
                    cả hai đều tô xanh nên không nút nào nổi lên là nút chính. */}
                {onFeedback && count > 0 && (
                  <button
                    onClick={onFeedback}
                    disabled={feedbackLoading}
                    title="Trộn embedding các frame trong giỏ câu này với query hiện tại rồi tìm lại"
                    className="inline-flex w-full items-center justify-center gap-1.5 rounded-xl border border-slate-300 bg-white py-1.5 text-[11.5px] font-semibold text-slate-600 transition-colors hover:border-blue-300 hover:text-blue-700 disabled:text-slate-400"
                  >
                    <RefreshIcon className={`w-4 h-4 ${feedbackLoading ? "animate-spin" : ""}`} />
                    {feedbackLoading ? "Đang tìm…" : `Tìm tương tự cho câu ${current} · ${count} frame`}
                  </button>
                )}
                <button
                  onClick={() => setSheetOpen(true)}
                  title={`Đóng gói ${answeredCount} câu đã có đáp án vào một file zip để nộp`}
                  className="flex w-full items-center gap-2.5 rounded-xl bg-blue-600 px-3 py-2 text-left text-white transition-colors hover:bg-blue-700"
                >
                  <UploadIcon className="w-[18px] h-[18px] shrink-0" />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] font-semibold">
                      Nộp bài cả đề · {answeredCount}/{numQuestions} câu
                    </span>
                    <span className="block text-[10.5px] leading-tight text-white/70">
                      {answeredCount > 0
                        ? `Gói ${answeredCount} file CSV vào một file .zip - nộp tất cả cùng lúc`
                        : "Chưa câu nào có đáp án"}
                    </span>
                  </span>
                  {errCount > 0 && (
                    <span className="shrink-0 rounded-full bg-red-500 px-1.5 py-0.5 text-[10px] font-bold tabular-nums">
                      {errCount}
                    </span>
                  )}
                </button>
              </footer>
            </div>

            <SubmitSheet
              open={sheetOpen}
              onClose={() => setSheetOpen(false)}
              basket={basket}
              answeredCount={answeredCount}
              issues={issues}
              issuesByQ={issuesByQ}
              emptyQids={emptyQids}
              blocked={blocked}
              errCount={errCount}
              exports={exports}
              onOpenCsv={() => setCsvOpen(true)}
              current={current}
              queryId={queryId}
              count={count}
              log={log}
              room={room}
              usedAttempts={usedAttempts}
              zipName={zipName}
              busy={busy}
              msg={msg}
              onExportZip={handleExportZip}
              onRedownload={handleRedownload}
              showLog={showLog}
              setShowLog={setShowLog}
            />

            {/* Nằm TRONG <aside>: khay đáp án đóng khi bấm ra ngoài, mà modal
                này phủ kín màn hình - để ngoài thì mỗi cú bấm trong modal cũng
                là "bấm ra ngoài khay" và đóng luôn cả drawer bên dưới. */}
            <CsvPreviewModal
              open={csvOpen}
              onClose={() => setCsvOpen(false)}
              exports={exports}
              questions={questionList}
              current={current}
              zipName={zipName}
              answeredCount={answeredCount}
              blocked={blocked}
              busy={busy}
              onExportZip={handleExportZip}
            />
          </>
        )}
      </aside>
    </div>
  );
}

export default SubmissionPanel;
