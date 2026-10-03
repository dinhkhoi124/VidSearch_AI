// src/components/VideoPlayerModal.jsx
//
// Hai vai: xem lại một frame trong video, và - khi có prop `pick` - CHỐT số
// frame cho một mục trong giỏ đáp án. Vai thứ hai có mặt vì keyframe trong index
// là thưa: khoảnh khắc đúng của đáp án thường không có keyframe nào, nên không
// chọn được từ lưới kết quả lẫn từ cửa sổ chuỗi frame. Trước đây chỉ đọc được số
// frame ở footer rồi phải tự nhớ, vì không có chỗ nào gõ nó vào.
import { useState, useEffect, useRef, useCallback } from 'react';
import { CloseIcon, CheckIcon } from './Icons';
import { fmtTime, fmtShot } from '../utils/frameIndex';
import { localizeMediaUrl } from '../utils/mediaUrl';

// Lấy ID video YouTube từ watch_url (watch?v=, youtu.be/, /embed/)
function getYouTubeId(url) {
  if (!url) return null;
  const m = String(url).match(
    /(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([A-Za-z0-9_-]{11})/
  );
  return m ? m[1] : null;
}

// Bước tua nhanh, tính bằng frame.
const JUMP = 10;

function VideoPlayerModal({ videoData, onClose, pick, onPickFrame }) {
  const videoRef = useRef(null);
  const [currentFrameIndex, setCurrentFrameIndex] = useState(0);
  // --- THÊM LẠI: State để lưu frame name ---
  const [currentFrameName, setCurrentFrameName] = useState("");
  // Số frame vừa chốt - để báo đã ghi mà KHÔNG đóng modal (còn nudge tiếp ±1).
  const [picked, setPicked] = useState(null);
  const [goto, setGoto] = useState("");

  // videoData tới từ hai đường: kết quả search (đã localize ở interceptor của
  // apiClient) và mục trong giỏ dùng chung (video_url là URL tuyệt đối của
  // NGƯỜI ĐÃ THÊM - xem basketReducer.toEntry). Đường thứ hai không phân giải
  // được nếu đồng đội mở app ở origin khác mình, nên localize lại ở đây.
  // localizeMediaUrl idempotent: đường thứ nhất không đổi gì.
  const videoUrl = localizeMediaUrl(videoData.video_url);
  // watch_url YouTube không chứa '/media/' nên localizeMediaUrl trả nguyên xi.
  const youTubeId = getYouTubeId(videoUrl);
  const startSec = Math.floor((videoData.timestamp_ms || 0) / 1000);
  const fps = Number(videoData.fps) || 0;
  // Tua từng frame chỉ có nghĩa khi biết fps VÀ có thẻ <video> để đặt
  // currentTime: iframe YouTube không cho đọc/đặt thời gian nên nhánh đó không
  // chốt frame được.
  const canStep = !youTubeId && fps > 0;

  useEffect(() => {
    const videoElement = videoRef.current;
    if (!videoElement) return;   // YouTube iframe -> bỏ qua (không có <video>)

    // Tự động tua đến đúng timestamp. Guard || 0 vì mục lấy từ giỏ đáp án có
    // thể mang timestamp_ms = null (useAnswerBasket.toEntry) -> seek NaN.
    const handleLoadedMetadata = () => {
      videoElement.currentTime = (videoData.timestamp_ms || 0) / 1000;
    };

    // Cập nhật frame index và frame name khi video chạy
    const handleTimeUpdate = () => {
      if (!videoData.fps) return;
      const currentTime = videoElement.currentTime;
      // +1e-6 trước khi floor: keyframe có timestamp_ms = frame/fps*1000 đúng
      // chính xác, nên tua tới mốc đó rồi floor số thực trần trụi hay rơi vào
      // 122.99999… -> trả về frame TRƯỚC. Lệch một frame là mất điểm cả dòng.
      const frameNumber = Math.floor(currentTime * videoData.fps + 1e-6);

      // Cập nhật cả hai state
      setCurrentFrameIndex(frameNumber);

      const formattedFrameNumber = String(frameNumber).padStart(6, '0');
      setCurrentFrameName(`${formattedFrameNumber}.webp`);
    };

    videoElement.addEventListener('loadedmetadata', handleLoadedMetadata);
    videoElement.addEventListener('timeupdate', handleTimeUpdate);

    return () => {
      videoElement.removeEventListener('loadedmetadata', handleLoadedMetadata);
      videoElement.removeEventListener('timeupdate', handleTimeUpdate);
    };
  }, [videoData]);

  // Nhảy tới đúng một frame. Pause trước: video đang chạy thì vừa seek xong nó
  // đã trôi sang frame khác, không soi được khung hình nào cả.
  const seekToFrame = useCallback((n) => {
    const el = videoRef.current;
    if (!el || !(fps > 0)) return;
    const target = Math.max(0, Math.round(n));
    el.pause();
    el.currentTime = target / fps;
    // timeupdate cũng bắn sau khi seek, nhưng đặt luôn để nút bấm phản hồi tức thì.
    setCurrentFrameIndex(target);
    setCurrentFrameName(`${String(target).padStart(6, '0')}.webp`);
  }, [fps]);

  const step = useCallback((d) => seekToFrame(currentFrameIndex + d), [seekToFrame, currentFrameIndex]);

  const commitPick = useCallback(() => {
    if (!onPickFrame) return;
    onPickFrame(currentFrameIndex);
    setPicked(currentFrameIndex);
  }, [onPickFrame, currentFrameIndex]);

  // Phím tắt của riêng modal, bắt ở pha CAPTURE + stopPropagation: ←/→ và Enter
  // không được lọt xuống handler toàn cục của SearchPage (Enter ở đó chạy lại
  // truy vấn). Cùng khuôn với lớp zoom của FrameSequenceModal.
  useEffect(() => {
    if (!canStep) return undefined;
    const onKeyDownCapture = (e) => {
      // Đang gõ trong ô "đi tới frame" thì phím là của ô đó.
      if (e.target instanceof HTMLInputElement) return;
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        e.preventDefault();
        e.stopPropagation();
        step((e.key === 'ArrowLeft' ? -1 : 1) * (e.shiftKey ? JUMP : 1));
      } else if (e.key === 'Enter' && onPickFrame) {
        e.preventDefault();
        e.stopPropagation();
        commitPick();
      } else if (e.key === ' ') {
        e.preventDefault();
        e.stopPropagation();
        const el = videoRef.current;
        if (el) el.paused ? el.play() : el.pause();
      }
    };
    window.addEventListener('keydown', onKeyDownCapture, true);
    return () => window.removeEventListener('keydown', onKeyDownCapture, true);
  }, [canStep, step, commitPick, onPickFrame]);

  // Frame đang lưu của mục sẽ được ghi đè, và độ lệch so với frame đang xem.
  const pickCurrent = pick?.frame_idx ?? null;
  const pickDelta = pickCurrent == null ? null : currentFrameIndex - pickCurrent;

  const STEP_BTN =
    "rounded-lg border border-slate-300 bg-white px-2 py-1 text-[11.5px] font-semibold text-slate-600 tabular-nums transition-colors hover:border-blue-400 hover:text-blue-700 disabled:opacity-40";

  return (
    // Lớp phủ nền. z-[90] để nằm TRÊN drawer giỏ đáp án (z-[70]) - mở video còn
    // được gọi từ trong giỏ để soát lại đáp án trước khi nộp.
    <div className="fixed inset-0 bg-slate-900/70 flex items-center justify-center z-[90] p-4" onClick={onClose}>
      <div
        className="bg-white rounded-xl shadow-2xl w-full max-w-5xl flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="p-3 text-slate-800 font-semibold text-lg border-b border-slate-200 flex justify-between items-center">
          <div className="flex items-baseline space-x-3">
            <span>{videoData.video_name}</span>
            {/* Mốc của frame được chọn - nhánh YouTube không cập nhật được
                footer nên đây là chỗ duy nhất cho biết đang mở ở đoạn nào. */}
            <span className="text-sm font-semibold text-blue-600 tabular-nums" title="Mốc của frame đã chọn">
              @ {fmtTime(videoData.timestamp_ms)}
            </span>
            <span className="text-sm font-normal text-slate-400 tabular-nums">{currentFrameName}</span>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100"><CloseIcon className="w-5 h-5" /></button>
        </div>

        {/* Video Player: YouTube -> iframe embed (nhảy tới đúng giây), local -> <video> */}
        {youTubeId ? (
          <iframe
            className="w-full aspect-video"
            src={`https://www.youtube.com/embed/${youTubeId}?start=${startSec}&autoplay=1`}
            title={videoData.video_name}
            allow="autoplay; encrypted-media; picture-in-picture"
            allowFullScreen
          />
        ) : (
          <video ref={videoRef} src={videoUrl} controls autoPlay className="w-full" />
        )}

        {/* Thanh tua theo FRAME. Đây là thứ biến trình phát thành công cụ chốt
            đáp án: kéo thanh trượt của <video> chỉ tới được từng phần giây, mà
            một giây có tới fps frame. */}
        {canStep && (
          <div className="flex flex-wrap items-center gap-2 border-t border-slate-200 bg-white px-3 py-2">
            <div className="flex items-center gap-1">
              <button onClick={() => step(-JUMP)} title={`Lùi ${JUMP} frame (Shift+←)`} className={STEP_BTN}>−{JUMP}</button>
              <button onClick={() => step(-1)} title="Lùi 1 frame (←)" className={STEP_BTN}>−1</button>
              <button onClick={() => step(+1)} title="Tiến 1 frame (→)" className={STEP_BTN}>+1</button>
              <button onClick={() => step(+JUMP)} title={`Tiến ${JUMP} frame (Shift+→)`} className={STEP_BTN}>+{JUMP}</button>
            </div>
            <div className="text-2xl font-bold text-slate-800 tabular-nums" title="Frame đang xem">
              {currentFrameIndex}
            </div>
            <span className="text-[11.5px] text-slate-400 tabular-nums">{fmtTime(currentFrameIndex / fps * 1000)}</span>
            <form
              onSubmit={(e) => { e.preventDefault(); if (goto.trim() !== "") seekToFrame(Number(goto)); }}
              className="ml-auto flex items-center gap-1"
            >
              <input
                type="number"
                min="0"
                value={goto}
                onChange={(e) => setGoto(e.target.value)}
                placeholder="đi tới frame"
                className="w-28 rounded-lg border border-slate-300 px-2 py-1 text-[11.5px] tabular-nums focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
              />
              <button type="submit" className={STEP_BTN}>Tới</button>
            </form>
          </div>
        )}

        {/* Khối CHỐT FRAME - chỉ có khi mở từ một dòng trong giỏ đáp án. */}
        {pick && onPickFrame && (
          canStep ? (
            <div className="flex flex-wrap items-center gap-3 border-t border-blue-200 bg-blue-50 px-3 py-2.5">
              <div className="min-w-0 text-[11.5px] leading-tight text-slate-600">
                <div className="font-semibold text-slate-700">
                  Câu {pick.qid}{pick.rank ? ` · hạng ${pick.rank}` : ""}
                </div>
                <div className="tabular-nums text-slate-500">
                  đang là {pickCurrent ?? "-"}
                  {pickDelta != null && pickDelta !== 0 && ` · Δ${pickDelta > 0 ? "+" : ""}${pickDelta}`}
                </div>
              </div>
              {picked != null && (
                <span className="inline-flex items-center gap-1 rounded-lg bg-emerald-100 px-2 py-1 text-[11.5px] font-semibold text-emerald-700 tabular-nums">
                  <CheckIcon className="w-3.5 h-3.5" /> đã ghi {picked}
                </span>
              )}
              {/* Không đóng modal sau khi chốt: gần như lần nào cũng phải nhích
                  thêm ±1 rồi chốt lại, đóng ra mở vào mỗi lần mới là chỗ tốn
                  thời gian nhất của quy trình cũ. */}
              <button
                onClick={commitPick}
                title="Ghi số frame đang xem vào dòng này trong giỏ (Enter)"
                className="ml-auto inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3.5 py-2 text-sm font-semibold text-white transition-colors hover:bg-blue-700"
              >
                Chốt frame {currentFrameIndex} cho câu {pick.qid}
              </button>
            </div>
          ) : (
            <div className="border-t border-amber-200 bg-amber-50 px-3 py-2 text-[11.5px] text-amber-800">
              {youTubeId
                ? "Video này phát qua YouTube nên không đọc/đặt được số frame — không chốt frame từ đây được."
                : "Frame này không có fps nên không quy đổi được thời gian ↔ số frame."}
            </div>
          )
        )}

        {/* Footer: thông tin frame index và FPS */}
        <div className="p-3 text-slate-600 text-sm bg-slate-50 border-t border-slate-200 flex justify-between items-center">
          <div className="flex items-baseline gap-4">
            <span>
              <span className="font-semibold text-slate-700">Frame index hiện tại:</span>{" "}
              <span className="tabular-nums">{currentFrameIndex}</span>
            </span>
            {/* Khoảng shot: cho biết frame nằm ở đâu trong cảnh, không chỉ một mốc giây */}
            {fmtShot(videoData) && (
              <span title="Khoảng thời gian của shot chứa frame này">
                <span className="font-semibold text-slate-700">Shot:</span>{" "}
                <span className="tabular-nums">{fmtShot(videoData)}</span>
              </span>
            )}
            {canStep && (
              <span className="text-[11.5px] text-slate-400">
                ← / → tua 1 frame · Shift = {JUMP} · Space play/pause
              </span>
            )}
          </div>
          {videoData.fps && (
            <div>
              <span className="font-semibold text-slate-700">FPS:</span> <span className="tabular-nums">{videoData.fps}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default VideoPlayerModal;
