// src/components/submission/PanelHeader.jsx
// Mọi thứ nằm TRÊN danh sách đáp án: hàng tiêu đề, dải cấu hình, chỉ báo TRAKE
// và đề bài BTC.
//
// MỘT khối trắng duy nhất, các thành phần bên trong là thẻ thụt vào lề (xem
// tokens.js) - không phải bốn dải full-bleed chồng lên nhau mỗi dải một nền như
// trước. Ở khay rộng 36rem thì bốn đường kẻ ngang trong 100px đầu làm phần đầu
// khay trông vụn hơn cả danh sách đáp án bên dưới.
//
// HAI popover, HAI phạm vi tách bạch - đây là điểm dễ nhầm nhất của khay này:
//   ⚙ (góc phải hàng tiêu đề) -> CẢ BỘ ĐỀ: số câu, nhập gói đề, xoá sạch. Nội
//     dung ở DeckMenu.jsx.
//   "Sửa" (cuối dải cấu hình)  -> RIÊNG CÂU ĐANG MỞ: Query ID, Max, số event.
//     Neo ngay dưới chữ "Sửa" chứ không bật lên tận góc trên như trước.
// Cấu hình của câu chỉ chỉnh lúc đầu vòng nên thu vào popover; dải mờ một dòng
// vẫn cho thấy tên file sắp nộp - thứ sai là hỏng cả câu - mà chỉ tốn một dòng
// thay vì bốn ô nhập.
import { useEffect, useState } from "react";
import {
  TASK_TYPES, TASK_LABEL, TASK_SHORT, MAX_ROWS,
} from "../../utils/submissionFormat";
import { copyText } from "../../utils/clipboard";
import { TrakeProgress } from "../QuestionSwitcher";
import Popover from "../ui/Popover";
import DeckMenu from "./DeckMenu";
import ConfirmAction from "./ConfirmAction";
import { InlineField, INPUT } from "./fields";
import { PAD_X, LABEL, META, ICON_BTN, MINI_BTN } from "./tokens";
import {
  InboxIcon, CloseIcon, ChevronDownIcon, SettingsIcon, TrashIcon, CopyIcon, CheckIcon,
} from "../Icons";

// `minimal`: dùng ở màn hình thiết lập - lúc chưa nhập đề thì Query ID, Max,
// đề bài đều chưa có nghĩa gì, hiện ra chỉ làm loãng việc duy nhất cần làm.
function PanelHeader({
  basket, onClose, onReopenSetup, onResetDeck, answeredCount, attempts, roomActive,
  deckOpen, setDeckOpen, editOpen, setEditOpen, hasPackage = false, minimal = false,
}) {
  const { current, count, taskType, queryId, maxRows, numEvents, queryText } = basket;
  const [taskOpen, setTaskOpen] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [copied, setCopied] = useState(false);

  // Nhãn "Đã chép" tự tắt sau 1.5s, và tắt ngay khi chuyển câu - nếu không thì
  // sang câu khác vẫn thấy báo đã chép trong khi đề trên tay là đề câu cũ.
  useEffect(() => setCopied(false), [current]);
  useEffect(() => {
    if (!copied) return undefined;
    const t = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(t);
  }, [copied]);

  const handleCopyDe = async () => {
    if (await copyText(queryText)) setCopied(true);
  };

  const tag = TASK_SHORT[taskType] || taskType;
  // Số event là thứ BẮT BUỘC phải đúng với TRAKE: số cột mỗi dòng CSV phải khớp
  // số event của đề, nên thiếu nó thì không đóng gói được câu này.
  const needsEvents = taskType === "trake" && !numEvents;

  const closeEdit = () => { setEditOpen(false); setConfirmClear(false); };

  return (
    <div className="shrink-0 border-b border-slate-200 bg-white">
      <header className={`flex items-center gap-2 pt-2.5 ${PAD_X} ${minimal ? "pb-2.5" : "pb-1.5"}`}>
        <InboxIcon className="w-[17px] h-[17px] shrink-0 text-blue-600" />
        <span className="whitespace-nowrap text-[14.5px] font-semibold">
          Câu <span className="font-bold text-blue-600 tabular-nums">{current}</span>
        </span>

        <Popover
          open={taskOpen}
          onClose={() => setTaskOpen(false)}
          panelClass="left-0 top-full mt-1.5 w-32 p-1"
          panel={TASK_TYPES.map((t) => (
            <button
              key={t}
              onClick={() => { basket.setTaskType(t); setTaskOpen(false); }}
              className={`block w-full rounded-md px-2 py-1.5 text-left text-[11.5px] transition-colors hover:bg-slate-100 ${
                taskType === t ? "font-bold text-blue-600" : "text-slate-600"
              }`}
            >
              {TASK_LABEL[t]}
            </button>
          ))}
        >
          <button
            onClick={() => setTaskOpen((v) => !v)}
            title={`${TASK_LABEL[taskType]} - áp dụng cho câu ${current}`}
            className={`flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider transition-colors ${
              taskType === "trake"
                ? "bg-violet-100 text-violet-700 hover:bg-violet-200"
                : "bg-slate-100 text-slate-600 hover:bg-slate-200"
            }`}
          >
            {tag}
            <ChevronDownIcon className="w-2.5 h-2.5" />
          </button>
        </Popover>

        <span className={`whitespace-nowrap ${META}`}>{count} đáp án</span>

        <div className="ml-auto flex items-center gap-0.5">
          <Popover
            open={deckOpen}
            onClose={() => setDeckOpen(false)}
            panelClass="right-0 top-full mt-1.5 w-72 p-3"
            panel={
              <DeckMenu
                basket={basket}
                answeredCount={answeredCount}
                attempts={attempts}
                roomActive={roomActive}
                onReopenSetup={onReopenSetup}
                onResetDeck={onResetDeck}
                onClose={() => setDeckOpen(false)}
              />
            }
          >
            <button
              onClick={() => setDeckOpen((v) => !v)}
              title="Cấu hình cả bộ đề: số câu, nhập gói đề, tạo đề mới"
              className={ICON_BTN}
            >
              <SettingsIcon className="w-4 h-4" />
            </button>
          </Popover>

          <button onClick={onClose} title="Đóng (Esc)" className={ICON_BTN}>
            <CloseIcon className="w-4 h-4" />
          </button>
        </div>
      </header>

      {!minimal && (
        <>
          {/* Tên file sắp nộp + hạn mức: đọc lướt một dòng là biết đúng hay sai.
              Luôn hiện, kể cả khi câu TRAKE còn thiếu event - trước đây dải này
              bị thẻ báo lỗi thay chỗ, nên đúng lúc đang sửa cấu hình thì lại
              không thấy tên file. */}
          <div className={`flex items-center gap-1.5 pb-2 ${PAD_X} ${META}`}>
            <span className="truncate font-semibold text-slate-500">{queryId}</span>
            <span className="text-slate-300">·</span>
            <span className="whitespace-nowrap">Max {maxRows}</span>
            {numEvents > 0 && (
              <>
                <span className="text-slate-300">·</span>
                <span className="whitespace-nowrap">{numEvents} event</span>
              </>
            )}
            {/* Popover neo ở ĐÂY, dưới chính chữ "Sửa" - không mượn chỗ của ⚙. */}
            <Popover
              open={editOpen}
              onClose={closeEdit}
              className="relative ml-auto shrink-0"
              panelClass="right-0 top-full mt-1.5 w-72 p-3"
              panel={
                <div className="space-y-2">
                  <div className={LABEL}>Câu {current} · {tag}</div>

                  <InlineField label="ID" hint={`Tên file nộp cho câu ${current} - phải khớp tên truy vấn BTC`}>
                    <input
                      type="text"
                      value={queryId}
                      onChange={(e) => basket.setQueryId(e.target.value)}
                      placeholder={`query-${current}-${taskType}`}
                      className={INPUT}
                    />
                  </InlineField>

                  <div className={`grid gap-2 ${taskType === "trake" ? "grid-cols-2" : "grid-cols-1"}`}>
                    <InlineField label="Max" hint={`Số dòng tối đa (BTC giới hạn ${MAX_ROWS})`}>
                      <input
                        type="number"
                        min="1"
                        max={MAX_ROWS}
                        value={maxRows}
                        onChange={(e) => basket.setMaxRows(e.target.value)}
                        className={`${INPUT} tabular-nums`}
                      />
                    </InlineField>
                    {taskType === "trake" && (
                      <InlineField label="Event" hint="Số event của chuỗi - mỗi dòng nộp phải có đúng bấy nhiêu frame">
                        <input
                          type="number"
                          min="1"
                          value={numEvents ?? ""}
                          onChange={(e) => basket.setNumEvents(e.target.value)}
                          placeholder="?"
                          className={`${INPUT} tabular-nums`}
                        />
                      </InlineField>
                    )}
                  </div>

                  {count > 0 && (
                    <div className="border-t border-slate-100 pt-2">
                      {confirmClear ? (
                        <ConfirmAction
                          title={`Xoá toàn bộ ${count} đáp án của câu ${current}?`}
                          detail="Chỉ câu này, các câu khác giữ nguyên. Không hoàn tác được."
                          confirmLabel={`Xoá ${count} đáp án`}
                          onCancel={() => setConfirmClear(false)}
                          onConfirm={() => { basket.clearQuestion(current); closeEdit(); }}
                        />
                      ) : (
                        <button
                          onClick={() => setConfirmClear(true)}
                          className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-[11.5px] text-red-600 transition-colors hover:bg-red-50"
                        >
                          <TrashIcon className="w-3.5 h-3.5 shrink-0" />
                          Xoá {count} đáp án của câu {current}
                        </button>
                      )}
                    </div>
                  )}
                </div>
              }
            >
              <button
                onClick={() => (editOpen ? closeEdit() : setEditOpen(true))}
                title={`Sửa cấu hình riêng câu ${current} (Query ID, Max${taskType === "trake" ? ", số event" : ""})`}
                className={`${MINI_BTN} text-blue-600 hover:bg-blue-50`}
              >
                Sửa
              </button>
            </Popover>
          </div>

          {/* Lỗi chặn nộp: thẻ đỏ thụt lề như các thẻ khác, nhưng là thứ duy
              nhất trong khối đầu được tô nền màu -> không thể lướt qua. */}
          {needsEvents && (
            <div className={`mb-2 flex items-center gap-2 rounded-xl border border-red-300 bg-red-50 px-2.5 py-1.5 mx-3`}>
              <span className="text-[11.5px] font-semibold text-red-600">
                Chưa khai số event - chưa đóng gói được câu này
              </span>
              <input
                type="number"
                min="1"
                value={numEvents ?? ""}
                onChange={(e) => basket.setNumEvents(e.target.value)}
                placeholder="?"
                title="Số event của chuỗi TRAKE"
                className="ml-auto w-14 rounded-lg border border-red-400 bg-white px-2 py-0.5 text-center text-[11.5px] font-bold text-red-600 tabular-nums focus:outline-none focus:ring-2 focus:ring-red-500/25"
              />
            </div>
          )}

          {/* Phím `a` tiếp theo sẽ điền vào event nào của ứng viên nào. Chỉ báo
              này vốn nằm ở pill nổi, mà pill bị ẩn khi khay mở -> đưa vào đây. */}
          {taskType === "trake" && numEvents > 0 && (
            <div className={`pb-2 ${PAD_X}`}>
              <TrakeProgress count={count} numEvents={numEvents} flat />
            </div>
          )}

          {/* Đề bài BTC - đọc ngay trong app, khỏi alt-tab.
              Luôn hiện đủ (cuộn trong thẻ) thay vì thu gọn được: đề là thứ phải
              liếc lại liên tục trong lúc lọc frame, gập vào rồi mở ra tốn đúng
              một cú bấm mỗi lần. Chỗ đó dành cho nút CHÉP - đề còn phải dán sang
              ô tìm kiếm, sang bản dịch, sang chat nhóm. */}
          {queryText && (
            <div className="mx-3 mb-2.5 rounded-xl border border-slate-200 bg-slate-50/70 px-2.5 py-1.5">
              <div className="mb-1 flex items-center gap-2">
                <span className={LABEL}>Đề câu {current}</span>
                <button
                  onClick={handleCopyDe}
                  title={`Chép đề câu ${current} vào clipboard`}
                  className={`${MINI_BTN} ml-auto ${
                    copied ? "text-emerald-600" : "text-slate-400 hover:bg-white hover:text-blue-600"
                  }`}
                >
                  {copied ? <CheckIcon className="w-3.5 h-3.5" /> : <CopyIcon className="w-3.5 h-3.5" />}
                  {copied ? "Đã chép" : "Chép"}
                </button>
              </div>
              <p className="max-h-28 select-text overflow-y-auto whitespace-pre-wrap text-[11.5px] leading-relaxed text-slate-700">
                {queryText}
              </p>
            </div>
          )}

          {/* Đã nhập gói đề mà câu này không có đề -> nói thẳng. Im lặng không
              hiện gì thì không phân biệt được "gói vốn thiếu câu này" (gói thật
              khuyết câu 3) với "chưa nhập đề", mà hai chuyện đó khác hẳn nhau. */}
          {!queryText && hasPackage && (
            <div className="mx-3 mb-2.5 rounded-xl border border-dashed border-slate-300 px-2.5 py-1.5 text-[11px] text-slate-400">
              Câu {current} không có trong gói đề đã nhập - kiểm tra lại số câu hoặc nhập bù file đề.
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default PanelHeader;
