// src/components/submission/AnswerList.jsx
// Danh sách đáp án đã xếp hạng của CÂU HIỆN TẠI - vùng cuộn duy nhất của khay,
// và là thứ được nhìn nhiều nhất trong lúc thi nên được ưu tiên chiều cao.
import { memo, useEffect, useRef, useState } from "react";
import { MAX_ANSWER_LEN, charLen, normalizeAnswer } from "../../utils/submissionFormat";
import { useDebouncedCommit } from "../../hooks/useDebouncedCommit";
import { memberColor } from "../../utils/memberStyle";
import { fmtTime } from "../../utils/frameIndex";
import { localizeMediaUrl } from "../../utils/mediaUrl";
import {
  InboxIcon, CloseIcon, ChevronUpIcon, ChevronDownIcon, PlayIcon, FilmIcon, RefreshIcon,
} from "../Icons";
import ManualFrameAdd from "./ManualFrameAdd";

/**
 * Một dòng đáp án.
 *
 * Số frame ở đây CHỈ ĐỌC - có chủ ý. Đã thử làm nó thành ô nhập tại chỗ và bỏ:
 * ô số nằm trong vùng cuộn thì chỉ cần lăn chuột đi qua là giá trị đổi, âm thầm,
 * mà đó đúng là con số đem nộp. Hai đường sửa còn lại đều là hành động CÓ CHỦ Ý:
 * chốt lại frame trong trình phát (bấm ảnh), hoặc thêm hẳn một dòng mới bằng
 * ManualFrameAdd.
 *
 * memo() ở đây chỉ có tác dụng vì props toàn là giá trị ỔN ĐỊNH: các callback
 * lấy thẳng từ useAnswerBasket (đã useCallback, deps chỉ có dispatch/resolveQid)
 * và hai primitive roomActive/myMemberId. Đừng nhận lại nguyên cả `basket` hay
 * `room` - hai object đó dựng mới mỗi lần render nên memo sẽ vô hiệu, và gõ một
 * ký tự vào ô đáp án là vẽ lại cả trăm dòng kèm ảnh.
 */
const AnswerRow = memo(function AnswerRow({
  it, i, count, qid, taskType, numEvents, tl,
  onMove, onRemove, onSetFrame, onSetAnswer,
  onVideoClick, onFramesClick, onPickFrame, roomActive, myMemberId,
}) {
  // Frame của CÁI ẢNH đang hiện, khi nó khác frame sắp nộp. Có mặt trong hai
  // trường hợp: đã sửa tay số frame (số máy tự tính lúc thêm), hoặc dòng được
  // thêm thủ công (keyframe gần nhất). Cả hai đều cần cùng một cảnh báo.
  const orig = it.frame_idx0 ?? null;
  const edited = orig != null && it.frame_idx !== orig;
  const delta = edited ? it.frame_idx - orig : 0;

  // Ô đáp án tự giữ giá trị của chính nó thay vì đọc thẳng từ giỏ.
  //
  // Ở chế độ phòng, mỗi op set_answer được server phát ngược lại cho CHÍNH người
  // vừa gõ, và nhánh "question" trong useAnswerBasket ghi đè nguyên cả items -
  // khác với nhánh "snapshot" ngay bên trên, nó không đắp lại op đang chờ. Ô
  // input mà controlled thẳng bằng state đó thì mỗi echo về là giá trị bật ngược
  // về bản cũ: nuốt mất mấy ký tự vừa gõ và ném con trỏ về cuối dòng, gõ chèn vào
  // giữa một đáp án có sẵn gần như không làm nổi.
  const [text, setText] = useState(it.answer);
  const typing = useRef(false);
  // Chỉ nhận giá trị từ giỏ khi mình KHÔNG đang gõ (đồng đội sửa, hoặc nút "áp
  // dụng cho tất cả"). Đang gõ thì bản của mình là bản đúng.
  useEffect(() => {
    if (!typing.current) setText(it.answer);
  }, [it.answer]);

  // Gõ thì hiện ngay, nhưng op chỉ đi sau khi ngưng 400ms hoặc khi rời ô: một
  // câu trả lời 20 ký tự đi từ 20 vòng POST + broadcast xuống còn 1-2.
  // qid truyền tường minh: lúc flush do unmount (đổi câu giữa chừng) thì
  // resolveQid đã trỏ sang câu mới, gửi thiếu qid là chữ rơi nhầm câu.
  const { push, flush } = useDebouncedCommit((v) => onSetAnswer(it.id, v, qid));

  // Đếm trên ĐÚNG chuỗi sẽ nằm trong file, theo code point. Đọc từ `text` chứ
  // không phải từ giỏ - bộ đếm phải nhảy theo từng phím, không chờ debounce.
  const answerLen = charLen(normalizeAnswer(text));

  return (
    <li>
      {/* Vách ngăn giữa các ứng viên TRAKE: mỗi khối là MỘT dòng CSV */}
      {tl?.first && (
        <div className="mb-1 mt-2 flex items-center gap-2 first:mt-0">
          <span className="rounded bg-violet-100 px-1.5 py-0.5 text-[10px] font-bold text-violet-700">
            Đáp án #{tl.cand}
          </span>
          <span className="h-px flex-1 bg-violet-200" />
        </div>
      )}
      <div className="flex items-start gap-2.5 rounded-xl border border-slate-200 bg-white p-2 transition-colors hover:border-blue-300">
        <span
          className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold tabular-nums ${
            tl
              ? "bg-violet-100 text-violet-700"
              : i === 0
                ? "bg-blue-600 text-white"
                : "bg-slate-100 text-slate-500"
          }`}
          title={tl ? `Event ${tl.event}/${numEvents}` : `Hạng ${i + 1}`}
        >
          {tl ? tl.event : i + 1}
        </span>
        {/* Bấm ảnh = mở video Ở CHẾ ĐỘ CHỐT FRAME luôn, không phải chỉ xem.
            Trong giỏ thì mọi dòng đều là một mục có thể chốt, nên tách làm hai
            nút (ảnh để xem, "chốt" để chỉnh) chỉ là một nút thừa: khay chốt chỉ
            thêm một dải ở đáy trình phát, không ghi gì cho tới khi bấm nút. */}
        <button
          type="button"
          onClick={() => (onPickFrame ? onPickFrame(it, i + 1) : onVideoClick?.(it))}
          disabled={!(onPickFrame || onVideoClick) || !it.video_url}
          title={
            it.video_url
              ? `Mở video tại ${fmtTime(it.timestamp_ms)}${onPickFrame ? " — tua từng frame rồi chốt lại số" : ""}`
              : "Không có video cho frame này"
          }
          className="group relative aspect-[16/9] w-24 shrink-0 overflow-hidden rounded-md ring-1 ring-slate-200 disabled:cursor-default"
        >
          {/* localize lại: frame_url trong giỏ là URL TUYỆT ĐỐI của
              người đã thêm frame (toEntry chép thẳng từ kết quả search
              của họ). Giỏ dùng chung, nên nếu đồng đội mở app ở origin
              khác mình thì URL đó không phân giải được ở đây. Hàm này
              giữ phần /media/... và thay host về origin đang mở; gọi
              lại lần nữa là vô hại. */}
          <img src={localizeMediaUrl(it.frame_url)} alt={it.frame_name} className="h-full w-full object-cover" />
          {/* Ảnh là KEYFRAME, không phải frame sắp nộp - lệch nhau khi frame đã
              được chốt lại trong trình phát, hoặc dòng này thêm thủ công. Không
              nói rõ thì rất dễ tin vào cái ảnh mà quên mất số thật. */}
          {edited && (
            <span
              className="absolute left-0 top-0 rounded-br-md bg-amber-500 px-1 text-[9.5px] font-bold text-white tabular-nums"
              title={`Ảnh này là keyframe ${orig}; frame sắp nộp là ${it.frame_idx}`}
            >
              {delta > 0 ? `+${delta}` : delta}
            </span>
          )}
          {(onPickFrame || onVideoClick) && it.video_url && (
            <span className="absolute inset-0 flex items-center justify-center bg-slate-900/50 text-white opacity-0 transition-opacity group-hover:opacity-100">
              <PlayIcon className="w-6 h-6" />
            </span>
          )}
        </button>
        <div className="min-w-0 flex-1">
          <div className="truncate text-xs font-semibold text-slate-800">{it.video_name}</div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[11px] text-slate-400 tabular-nums">
            <span title={Number(it.fps) > 0 ? `${it.fps} fps` : "Không rõ fps"}>
              frame {it.frame_idx ?? "-"} · {fmtTime(it.timestamp_ms)}
            </span>
            {/* Xem dải frame liên tiếp NGAY TỪ TRONG giỏ: frame đã chốt
                thường lệch vài frame so với khoảnh khắc đúng, và cửa sổ
                chuỗi cho thêm/đổi frame lân cận ngay tại đó (mỗi ô là
                một ResultItem đủ nút thêm giỏ). Trước đây phải quay ra
                lưới kết quả tìm lại đúng frame đó mới mở được. */}
            {onFramesClick && (
              <button
                type="button"
                onClick={() => onFramesClick(it)}
                title="Xem các frame liên tiếp quanh frame này — thêm/đổi frame lân cận cho chính xác hơn"
                className="inline-flex items-center gap-1 rounded px-1 py-0.5 font-semibold text-slate-500 transition-colors hover:bg-blue-50 hover:text-blue-700"
              >
                <FilmIcon className="w-3 h-3" /> chuỗi
              </button>
            )}
            {edited && (
              <button
                type="button"
                onClick={() => onSetFrame(it.id, orig, qid)}
                title={`Số nộp là ${it.frame_idx}, còn ảnh bên trái là keyframe ${orig}. Bấm để nộp chính ${orig}`}
                className="inline-flex items-center gap-1 rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700 transition-colors hover:bg-amber-100"
              >
                <RefreshIcon className="w-3 h-3" /> dùng ảnh
              </button>
            )}
            {/* Ai chốt frame này. Chỉ hiện khi ở phòng VÀ không phải
                mình - tự mình thêm thì nhãn chỉ thêm nhiễu. */}
            {roomActive && it.added_by_name && it.added_by !== myMemberId && (
              <span
                className={`inline-flex items-center gap-1 rounded-full px-1.5 text-[10px] font-semibold text-white ${memberColor(it.added_by_name)}`}
                title={`${it.added_by_name} thêm frame này`}
              >
                {it.added_by_name}
              </span>
            )}
          </div>
          {taskType === "qa" && (
            <div className="relative mt-1">
              <input
                type="text"
                value={text}
                onChange={(e) => {
                  typing.current = true;
                  setText(e.target.value);
                  push(e.target.value);
                }}
                onBlur={() => {
                  typing.current = false;
                  flush();
                }}
                placeholder="Câu trả lời…"
                className={`w-full rounded-md border bg-white py-1 pl-2 pr-11 text-xs focus:outline-none focus:ring-2 ${
                  answerLen > MAX_ANSWER_LEN
                    ? "border-red-400 focus:border-red-500 focus:ring-red-500/20"
                    : "border-slate-300 focus:border-blue-500 focus:ring-blue-500/20"
                }`}
              />
              <span
                className={`pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-[10px] tabular-nums ${
                  answerLen > MAX_ANSWER_LEN ? "font-bold text-red-500" : "text-slate-300"
                }`}
              >
                {answerLen}/{MAX_ANSWER_LEN}
              </span>
            </div>
          )}
        </div>
        <div className="flex shrink-0 flex-col gap-0.5">
          <button
            onClick={() => onMove(it.id, -1, qid)}
            disabled={i === 0}
            title="Lên hạng"
            className="flex h-6 w-6 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-25 disabled:hover:bg-transparent"
          >
            <ChevronUpIcon className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => onMove(it.id, +1, qid)}
            disabled={i === count - 1}
            title="Xuống hạng"
            className="flex h-6 w-6 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-25 disabled:hover:bg-transparent"
          >
            <ChevronDownIcon className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => onRemove(it.id, qid)}
            title="Xoá khỏi giỏ"
            className="flex h-6 w-6 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600"
          >
            <CloseIcon className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </li>
  );
});

function AnswerList({
  basket, items, count, current, taskType, numEvents, trakeLabel,
  onVideoClick, onFramesClick, onPickFrame, room,
}) {
  // Bóc ra từng hàm một: `basket` là object dựng mới mỗi render, còn từng hàm
  // bên trong nó thì ổn định (useCallback trong useAnswerBasket). Truyền các hàm
  // này xuống thay vì cả cụm là điều kiện để memo(AnswerRow) có tác dụng.
  const { move, remove, setFrame, setAnswerText } = basket;
  const roomActive = room?.active === true;
  const myMemberId = room?.member?.id ?? null;

  // Q&A: một câu hỏi thường chỉ có MỘT đáp án đúng, chỉ khác frame bằng chứng.
  //
  // Đọc `items` từ giỏ chứ không phải từ ô đang gõ, nên phải chắc chắn ô đó đã
  // đẩy chữ mới nhất vào giỏ trước: bấm nút làm input blur TRƯỚC khi click chạy,
  // mà onBlur có flush() - đừng đổi nút này thành thứ không lấy focus
  // (onMouseDown + preventDefault chẳng hạn), làm thế là chép lại bản cũ.
  //
  // TODO: 1 op cho mỗi dòng - giỏ 100 dòng là 100 POST + 100 lượt broadcast. Gộp
  // thành một op cần thêm action ở cả basketReducer.js lẫn room_store.py.
  const applyAnswerToAll = () => {
    const first = items.find((it) => String(it.answer || "").trim());
    if (!first) return;
    for (const it of items) if (it.id !== first.id) setAnswerText(it.id, first.answer, current);
  };

  // MỘT cây JSX cho cả hai trường hợp rỗng/không rỗng. Trước đây câu rỗng đi qua
  // một nhánh return riêng, nên thêm dòng đầu tiên vào câu là nhảy nhánh ->
  // ManualFrameAdd bị unmount -> bay sạch bản nháp đang gõ dở của mọi câu.
  return (
    <div className="flex-1 overflow-y-auto p-3">
      {/* Phải có mặt cả khi giỏ RỖNG: câu chưa có dòng nào là đúng lúc cần nhất -
          không có gì để bấm + mà cũng không có dòng nào để sửa frame. */}
      <ManualFrameAdd basket={basket} current={current} />

      {count === 0 ? (
        <div className="mt-3 flex flex-col items-center gap-1.5 rounded-xl border border-dashed border-slate-300 bg-white/60 px-5 py-6 text-center">
          <InboxIcon className="w-7 h-7 text-slate-300" />
          <p className="text-[13px] font-semibold text-slate-500">Câu {current} chưa có đáp án</p>
          <p className="text-[11.5px] leading-relaxed text-slate-400">
            Nhấn <span className="font-semibold text-blue-600">+</span> trên kết quả tìm kiếm, hoặc phím{" "}
            <kbd className="rounded border border-slate-300 bg-slate-100 px-1 font-semibold text-slate-600">a</kbd>{" "}
            để thêm frame đang chọn.
          </p>
        </div>
      ) : (
        <>
          {taskType === "qa" && count > 1 && (
            <button
              onClick={applyAnswerToAll}
              title="Chép câu trả lời đầu tiên xuống mọi dòng - Q&A thường chỉ có một đáp án, khác nhau ở frame bằng chứng"
              className="mb-2 w-full rounded-xl border border-slate-200 bg-white py-1.5 text-[11.5px] font-semibold text-slate-600 transition-colors hover:border-blue-300 hover:text-blue-700"
            >
              Áp dụng câu trả lời đầu cho tất cả {count} dòng
            </button>
          )}

          <ul className="space-y-1.5">
            {items.map((it, i) => (
              <AnswerRow
                key={it.id}
                it={it}
                i={i}
                count={count}
                qid={current}
                taskType={taskType}
                numEvents={numEvents}
                tl={trakeLabel.get(it.id)}
                onMove={move}
                onRemove={remove}
                onSetFrame={setFrame}
                onSetAnswer={setAnswerText}
                onVideoClick={onVideoClick}
                onFramesClick={onFramesClick}
                onPickFrame={onPickFrame}
                roomActive={roomActive}
                myMemberId={myMemberId}
              />
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

export default AnswerList;
