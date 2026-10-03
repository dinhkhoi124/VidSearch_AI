// src/components/submission/ManualFrameAdd.jsx
// Thêm một dòng đáp án HOÀN TOÀN THỦ CÔNG: gõ tên video + số frame, hoặc gõ
// mốc thời gian (phút:giây) rồi để app quy ra số frame theo fps của video.
//
// Vì sao cần: ô sửa frame trong AnswerList chỉ sửa được dòng ĐÃ CÓ. Có trường
// hợp cả đoạn video chứa đáp án không lọt một keyframe nào vào kết quả tìm kiếm
// - lúc đó trong giỏ không có dòng nào để mà sửa, và cũng không có ô nào để bấm
// dấu +. Đây là đường duy nhất đưa frame đó vào bài nộp.
//
// Vì sao có ô phút/giây: khi soi bằng trình phát video, thứ đọc được là mốc
// thời gian chứ không phải số frame. frame = round(giây × fps) - đúng công thức
// ngược của timestamp_ms = frame / fps * 1000 mà backend dùng cho mọi keyframe,
// nên số quy ra khớp với số frame của chính bộ dữ liệu.
//
// Không cần endpoint mới: /frame_neighbors đã trả đủ fps + video_url + ảnh của
// keyframe GẦN NHẤT khi đưa cho nó một frame_name không tồn tại (nó tự dò theo
// khoảng cách số). Ảnh keyframe gần nhất dùng làm hình xem trước - kèm badge Δ
// để không ai nhầm nó là frame sắp nộp. Cũng chính endpoint đó cho biết fps của
// video (dò trước bằng một lần gọi window=1) để quy đổi thời gian.
//
// BẢN NHÁP RIÊNG CHO TỪNG CÂU: xem chú thích ở `drafts` bên dưới.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import apiClient from "../../api/apiClient";
import { fmtTime, parseFrameNumber } from "../../utils/frameIndex";
import { isValidFrameIdx } from "../../utils/submissionFormat";
import { PlusIcon, CloseIcon } from "../Icons";

// Tên keyframe theo quy ước của bộ dữ liệu: 6 chữ số, đuôi .webp.
const frameFileName = (n) => `${String(n).padStart(6, "0")}.webp`;

// Bản nháp rỗng của MỘT câu. Hằng ngoài component để mọi câu chưa đụng tới đều
// dùng chung một tham chiếu.
const EMPTY = { open: false, video: "", mode: "frame", frame: "", mm: "", ss: "", busy: false, msg: null };

function ManualFrameAdd({ basket, current }) {
  // Mỗi câu MỘT bản nháp riêng, không phải một bản dùng chung.
  //
  // Component này không bị unmount khi đổi câu, nên hồi trước 8 state rời nhau ở
  // đây chảy thẳng từ câu này sang câu kia: tên video gõ dở, số frame, tab đang
  // chọn, và cả dòng "Đã thêm ... vào câu 3" hiện chình ình khi đang đứng ở câu
  // 4. Giữ theo qid thay vì xoá trắng mỗi lần đổi câu vì mỗi câu là một mạch tìm
  // riêng - đang dò dở câu 3 mà lỡ bấm sang câu 4 rồi quay lại thì không phải gõ
  // lại "L26_V450" từ đầu.
  //
  // Cố ý KHÔNG nhét vào basket/state.questions: state đó đồng bộ với cả nhóm qua
  // room_store.py (xem đầu basketReducer.js), nhét chuỗi gõ dở vào là broadcast
  // từng ký tự cho 4 máy còn lại và phải thêm op tương ứng bên Python.
  const [drafts, setDrafts] = useState({}); // { [qid]: {...EMPTY} }
  const d = drafts[current] || EMPTY;

  const patch = useCallback((qid, fields) => {
    setDrafts((prev) => ({ ...prev, [qid]: { ...(prev[qid] || EMPTY), ...fields } }));
  }, []);

  // fps của video đang gõ: { state: "idle"|"loading"|"ok"|"err", fps }.
  // Giữ MỘT bản chứ không tách theo câu: nó là hàm thuần của tên video đang hiện,
  // effect bên dưới tự dò lại khi đổi câu (videoName đổi theo).
  const [fpsInfo, setFpsInfo] = useState({ state: "idle", fps: null });
  // Cache khoá theo TÊN VIDEO nên dùng chung cho mọi câu: gõ lại cùng một video ở
  // câu khác thì có fps ngay, không phải chờ mạng lần nữa.
  const fpsCache = useRef(new Map());

  // Gợi ý tên video từ chính những gì cả nhóm đã bỏ vào giỏ - gần như luôn là
  // video đang soi dở, và gõ tay "L29_V001" rất dễ sai một ký tự.
  const videoNames = useMemo(() => {
    const set = new Set();
    for (const q of Object.values(basket.questions || {})) {
      for (const it of q.items || []) if (it.video_name) set.add(it.video_name);
    }
    return [...set].sort();
  }, [basket.questions]);

  const videoName = d.video.trim();
  const frameNum = d.frame.trim();

  // Dò fps ngay khi tên video đứng yên: cần cho cả hai chiều quy đổi (gõ thời
  // gian ra frame, và hiện mốc thời gian của số frame vừa gõ). Debounce 350ms
  // để không bắn request theo từng phím.
  useEffect(() => {
    if (!d.open || !videoName) {
      setFpsInfo({ state: "idle", fps: null });
      return;
    }
    if (fpsCache.current.has(videoName)) {
      setFpsInfo({ state: "ok", fps: fpsCache.current.get(videoName) });
      return;
    }
    let alive = true;
    setFpsInfo({ state: "loading", fps: null });
    const t = setTimeout(async () => {
      try {
        const res = await apiClient.get("/frame_neighbors", {
          params: { video_name: videoName, frame_name: frameFileName(0), window: 1 },
        });
        const f = Number(res.data?.frames?.[0]?.fps) || 0;
        if (!alive) return;
        if (f > 0) {
          fpsCache.current.set(videoName, f);
          setFpsInfo({ state: "ok", fps: f });
        } else {
          setFpsInfo({ state: "err", fps: null });
        }
      } catch {
        if (alive) setFpsInfo({ state: "err", fps: null });
      }
    }, 350);
    return () => { alive = false; clearTimeout(t); };
  }, [d.open, videoName]);

  const fps = fpsInfo.state === "ok" ? fpsInfo.fps : 0;

  // Tổng số giây từ hai ô phút/giây. Giây cho phép số lẻ (12.5) vì đọc mốc từ
  // trình phát ra số lẻ là chuyện thường.
  const totalSec = useMemo(() => {
    if (d.mm.trim() === "" && d.ss.trim() === "") return null;
    const m = d.mm.trim() === "" ? 0 : Number(d.mm);
    const s = d.ss.trim() === "" ? 0 : Number(d.ss);
    if (!Number.isFinite(m) || !Number.isFinite(s) || m < 0 || s < 0) return null;
    return m * 60 + s;
  }, [d.mm, d.ss]);

  // Số frame thực sự sẽ nộp, tuỳ chế độ đang chọn.
  const effN = useMemo(() => {
    if (d.mode === "time") {
      if (totalSec == null || !(fps > 0)) return null;
      return Math.round(totalSec * fps);
    }
    return isValidFrameIdx(frameNum) ? Number(frameNum) : null;
  }, [d.mode, totalSec, fps, frameNum]);

  const ready = videoName !== "" && effN != null;

  const submit = async (e) => {
    e.preventDefault();
    if (!ready || d.busy) return;
    // Chốt câu NGAY TẠI ĐÂY rồi dùng suốt hàm. Request dưới kia mất vài trăm ms,
    // trong lúc đó người dùng có thể đã bấm sang câu khác - đọc `current` lúc
    // promise resolve thì frame hạ cánh nhầm câu, và basket.add() không truyền
    // qid cũng rơi về đúng cái bẫy đó (resolveQid lấy currentRef.current).
    const qid = current;
    const n = effN;
    // id tổng hợp, KHÔNG mượn id của keyframe gần nhất: mượn thì hai frame thủ
    // công quanh cùng một keyframe sẽ chèn nhau (giỏ chống trùng bằng id), và ô
    // keyframe đó ngoài lưới kết quả sẽ hiện "đã trong giỏ" một cách sai.
    const id = `manual:${videoName}_${n}`;

    const inQ = basket.questionOf(id);
    if (inQ != null) {
      patch(qid, {
        msg: { tone: "err", text: inQ === qid ? "Frame này đã có trong câu này." : `Frame này đã nằm ở câu ${inQ}.` },
      });
      return;
    }

    patch(qid, { busy: true, msg: null });
    try {
      // window=1 là nhỏ nhất endpoint cho phép (ge=1); lấy về tối đa 3 ô rồi tự
      // chọn ô gần số frame mình gõ nhất.
      const res = await apiClient.get("/frame_neighbors", {
        params: { video_name: videoName, frame_name: frameFileName(n), window: 1 },
      });
      const frames = res.data?.frames || [];
      if (!frames.length) throw new Error("Video này không có keyframe nào trong index.");
      const near = frames.reduce((best, f) => {
        const dist = Math.abs((parseFrameNumber(f.frame_name) ?? 0) - n);
        return dist < best.d ? { f, d: dist } : best;
      }, { f: frames[0], d: Infinity }).f;

      const nearFps = Number(near.fps) || 0;
      basket.add(
        {
          id,
          video_name: videoName,
          // Tên của frame MÌNH GÕ, không phải của keyframe gần nhất: nút "chuỗi"
          // mở ra sẽ căn quanh đúng chỗ này, và toEntry đọc frame_idx từ đây.
          frame_name: frameFileName(n),
          timestamp_ms: nearFps > 0 ? Math.round((n / nearFps) * 1000) : null,
          fps: near.fps ?? null,
          // Ảnh xem trước = keyframe gần nhất; frame_idx0 nói rõ nó là frame nào.
          frame_url: near.frame_url,
          video_url: near.video_url,
          frame_idx0: parseFrameNumber(near.frame_name),
        },
        qid
      );

      patch(qid, {
        ...(d.mode === "time" ? { ss: "" } : { frame: "" }),
        busy: false,
        msg: { tone: "ok", text: `Đã thêm ${videoName} · frame ${n} vào câu ${qid}.` },
      });
    } catch (err) {
      patch(qid, { busy: false, msg: { tone: "err", text: err.response?.data?.detail || err.message } });
    }
  };

  if (!d.open) {
    return (
      <button
        onClick={() => patch(current, { open: true })}
        title="Gõ tay tên video + số frame (hoặc mốc phút:giây) để tạo một dòng đáp án mới - dùng khi đoạn video đó không có keyframe nào trong kết quả tìm kiếm"
        className="mb-2 flex w-full items-center justify-center gap-1.5 rounded-xl border border-dashed border-slate-300 bg-white/60 py-1.5 text-[11.5px] font-semibold text-slate-500 transition-colors hover:border-blue-400 hover:text-blue-700"
      >
        <PlusIcon className="w-3.5 h-3.5" /> Thêm frame thủ công
      </button>
    );
  }

  const tabCls = (m) =>
    `rounded-md px-2 py-0.5 text-[10.5px] font-semibold transition-colors ${
      d.mode === m ? "bg-blue-600 text-white" : "text-slate-500 hover:bg-white hover:text-slate-700"
    }`;

  return (
    <form onSubmit={submit} className="mb-2 rounded-xl border border-blue-200 bg-blue-50/60 p-2">
      <div className="mb-1.5 flex items-center gap-2">
        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
          Thêm frame thủ công · câu {current}
        </span>
        <button
          type="button"
          onClick={() => patch(current, { open: false, msg: null })}
          title="Đóng"
          className="ml-auto flex h-5 w-5 items-center justify-center rounded text-slate-400 transition-colors hover:bg-white hover:text-slate-700"
        >
          <CloseIcon className="w-3.5 h-3.5" />
        </button>
      </div>

      <div className="mb-1.5 flex items-center gap-1 rounded-lg bg-white/70 p-0.5">
        <button type="button" onClick={() => patch(current, { mode: "frame" })} className={tabCls("frame")}>
          Số frame
        </button>
        <button type="button" onClick={() => patch(current, { mode: "time" })} className={tabCls("time")}>
          Phút : giây
        </button>
      </div>

      <div className="flex items-center gap-1.5">
        <input
          type="text"
          value={d.video}
          onChange={(e) => patch(current, { video: e.target.value })}
          list="aic-manual-videos"
          placeholder="L29_V001"
          autoFocus
          className="min-w-0 flex-1 rounded-lg border border-slate-300 bg-white px-2 py-1 text-[11.5px] font-semibold text-slate-700 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
        />
        <datalist id="aic-manual-videos">
          {videoNames.map((v) => <option key={v} value={v} />)}
        </datalist>

        {d.mode === "frame" ? (
          <input
            type="number"
            min="0"
            value={d.frame}
            onChange={(e) => patch(current, { frame: e.target.value })}
            placeholder="số frame"
            className="w-28 rounded-lg border border-slate-300 bg-white px-2 py-1 text-[11.5px] text-slate-700 tabular-nums focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
          />
        ) : (
          <div className="flex shrink-0 items-center gap-0.5">
            <input
              type="number"
              min="0"
              value={d.mm}
              onChange={(e) => patch(current, { mm: e.target.value })}
              placeholder="phút"
              className="w-14 rounded-lg border border-slate-300 bg-white px-2 py-1 text-[11.5px] text-slate-700 tabular-nums focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
            />
            <span className="text-[11.5px] font-semibold text-slate-400">:</span>
            <input
              type="number"
              min="0"
              step="0.01"
              value={d.ss}
              onChange={(e) => patch(current, { ss: e.target.value })}
              placeholder="giây"
              className="w-16 rounded-lg border border-slate-300 bg-white px-2 py-1 text-[11.5px] text-slate-700 tabular-nums focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
            />
          </div>
        )}

        <button
          type="submit"
          disabled={!ready || d.busy}
          className="shrink-0 rounded-lg bg-blue-600 px-3 py-1.5 text-[11.5px] font-semibold text-white transition-colors hover:bg-blue-700 disabled:bg-slate-200 disabled:text-slate-400"
        >
          {d.busy ? "Đang thêm…" : "Thêm"}
        </button>
      </div>

      {/* Dòng quy đổi: luôn cho thấy CẢ HAI đơn vị để đối chiếu trước khi thêm. */}
      <p className="mt-1.5 text-[10.5px] leading-snug text-slate-500 tabular-nums">
        {!videoName ? (
          "Nhập tên video để lấy fps."
        ) : fpsInfo.state === "loading" ? (
          "Đang lấy fps của video…"
        ) : fpsInfo.state === "err" ? (
          <span className="text-amber-600">
            Không lấy được fps của "{videoName}" (video không có trong index?).
            {d.mode === "time" && " Chuyển sang chế độ Số frame để nhập trực tiếp."}
          </span>
        ) : d.mode === "time" ? (
          effN != null
            ? <>fps {fps} · {fmtTime(totalSec * 1000)} = <b className="text-slate-700">frame {effN}</b></>
            : <>fps {fps} · nhập phút/giây để quy ra số frame.</>
        ) : effN != null ? (
          <>fps {fps} · frame {effN} = <b className="text-slate-700">{fmtTime((effN / fps) * 1000)}</b></>
        ) : (
          <>fps {fps} · nhập số frame.</>
        )}
      </p>

      {d.msg && (
        <p className={`mt-1 text-[10.5px] leading-snug ${d.msg.tone === "ok" ? "text-emerald-700" : "text-red-600"}`}>
          {d.msg.text}
        </p>
      )}
      <p className="mt-1 text-[10.5px] leading-snug text-slate-400">
        Ảnh hiện ra sẽ là keyframe GẦN NHẤT (kèm badge Δ), còn số nộp là số bạn gõ.
      </p>
    </form>
  );
}

export default ManualFrameAdd;
