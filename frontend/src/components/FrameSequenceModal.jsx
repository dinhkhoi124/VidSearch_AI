// src/components/FrameSequenceModal.jsx
// Hiển thị các keyframe liên tiếp quanh một frame để theo dõi diễn biến của video.
//
// Đây là chỗ DUY NHẤT chọn được frame khác với frame mà retriever trả về - quan
// trọng cho KIS/TRAKE, vì keyframe khớp truy vấn chưa chắc là frame nằm trong
// khoảng đáp án. Mỗi ô là một ResultItem đầy đủ (thêm giỏ / mở video / xem chuỗi)
// nhờ /frame_neighbors nay trả cả id + timestamp_ms.
import { useEffect, useRef, useState } from 'react';
import apiClient from '../api/apiClient';
import ResultItem from './ResultItem';
import { PlayIcon, CloseIcon } from './Icons';

// Số cột tương ứng mức "zoom": cột càng ít thì frame càng to.
const COL_LEVELS = [2, 3, 4, 5, 6, 8];

function FrameSequenceModal({
  frame,
  windowSize = 150, // KHÔNG đặt tên là `window`: prop sẽ che biến toàn cục window
  onClose,         // trong cả component, làm mọi addEventListener ở đây hỏng câm.
  onVideoClick,
  basket,
  isSeen,
}) {
  const [frames, setFrames] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');
  const [zoomUrl, setZoomUrl] = useState(null);
  const [cols, setCols] = useState(4); // mặc định 4 cột -> frame to hơn nhiều so với 8
  const currentRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setError('');
    apiClient
      .get('/frame_neighbors', {
        params: { video_name: frame.video_name, frame_name: frame.frame_name, window: windowSize },
      })
      .then((res) => {
        if (!cancelled) setFrames(res.data.frames || []);
      })
      .catch((err) => {
        if (!cancelled) setError(err.response?.data?.detail || err.message);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [frame, windowSize]);

  // ESC lúc đang phóng to chỉ được đóng lớp zoom. Không chặn ở đây thì handler
  // toàn cục của SearchPage đóng luôn cả modal và mất vị trí cuộn trong dải
  // 100 frame - đúng lúc đang soi để chốt đáp án. Bắt ở pha CAPTURE để chạy
  // trước listener bubble trong useHotkeys.
  useEffect(() => {
    if (!zoomUrl) return undefined;
    const onKeyDownCapture = (e) => {
      if (e.key !== 'Escape') return;
      e.stopPropagation();
      setZoomUrl(null);
    };
    window.addEventListener('keydown', onKeyDownCapture, true);
    return () => window.removeEventListener('keydown', onKeyDownCapture, true);
  }, [zoomUrl]);

  // Cuộn tới frame hiện tại sau khi render
  useEffect(() => {
    if (!isLoading && currentRef.current) {
      currentRef.current.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'center' });
    }
  }, [isLoading, frames]);

  // /frame_neighbors dựng dict thủ công ở backend, không nằm trong schema nào
  // -> không chắc field nào cũng có.
  const stripName = (name) => String(name ?? '').replace(/\.webp$/i, '');

  return (
    // z-[95]: modal này mở được TỪ TRONG khay giỏ đáp án (z-[70]) — đúng lúc
    // cần soi frame liên tiếp để chốt đáp án chính xác hơn. Để z-50 như cũ thì
    // nó nằm dưới khay và coi như không mở được. Trên cả VideoPlayerModal
    // (z-[90]) vì mở video từ đây sẽ đóng modal này trước.
    <div className="fixed inset-0 bg-slate-900/70 flex items-center justify-center z-[95] p-4" onClick={onClose}>
      <div
        className="bg-white rounded-xl shadow-2xl w-full max-w-7xl max-h-[92vh] flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="p-3 border-b border-slate-200 flex justify-between items-center">
          <div className="flex items-baseline space-x-3">
            <span className="text-slate-800 font-semibold text-lg">{frame.video_name}</span>
            <span className="text-sm text-slate-400">quanh frame {stripName(frame.frame_name)}</span>
          </div>
          <div className="flex items-center space-x-3">
            {/* Điều chỉnh kích thước frame (zoom lưới) */}
            <div className="flex items-center space-x-1">
              <button
                onClick={() => setCols((c) => COL_LEVELS[Math.min(COL_LEVELS.indexOf(c) + 1, COL_LEVELS.length - 1)])}
                disabled={cols >= COL_LEVELS[COL_LEVELS.length - 1]}
                title="Thu nhỏ frame"
                className="w-8 h-8 rounded bg-slate-100 hover:bg-slate-200 text-slate-700 text-lg leading-none disabled:opacity-40"
              >
                −
              </button>
              <button
                onClick={() => setCols((c) => COL_LEVELS[Math.max(COL_LEVELS.indexOf(c) - 1, 0)])}
                disabled={cols <= COL_LEVELS[0]}
                title="Phóng to frame"
                className="w-8 h-8 rounded bg-slate-100 hover:bg-slate-200 text-slate-700 text-lg leading-none disabled:opacity-40"
              >
                +
              </button>
            </div>
            {onVideoClick && (
              <button
                onClick={() => onVideoClick(frame)}
                className="inline-flex items-center gap-1.5 text-sm bg-blue-600 hover:bg-blue-700 text-white px-3 py-1.5 rounded-lg font-medium transition-colors"
              >
                <PlayIcon className="w-4 h-4" /> Mở video
              </button>
            )}
            <button onClick={onClose} className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100"><CloseIcon className="w-5 h-5" /></button>
          </div>
        </div>

        {/* Body: lưới các frame liên tiếp */}
        <div className="p-4 overflow-y-auto">
          {isLoading && <p className="text-center text-slate-400">Đang tải các frame liên tiếp…</p>}
          {!isLoading && error && <p className="text-center text-red-500">{error}</p>}
          {!isLoading && !error && (
            <div
              className="grid gap-2"
              style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
            >
              {frames.map((f) => (
                <div
                  key={f.frame_name}
                  ref={f.is_current ? currentRef : null}
                  className={`relative rounded-lg ${f.is_current ? 'ring-2 ring-blue-500 ring-offset-1' : ''}`}
                >
                  {/* Frame cũ (payload thiếu id) vẫn chỉ zoom được - không để vỡ
                      UI nếu backend chưa cập nhật. */}
                  {f.id ? (
                    <ResultItem
                      result={f}
                      onImageClick={(r) => setZoomUrl(r.frame_url)}
                      onVideoClick={(r) => onVideoClick?.(r)}
                      onFramesClick={null}
                      basketRank={basket?.rankOf(f.id) ?? null}
                      basketQuestion={basket?.questionOf(f.id) ?? null}
                      currentQuestion={basket?.current}
                      onToggleBasket={basket ? basket.toggle : undefined}
                      seen={isSeen?.(f.id)}
                    />
                  ) : (
                    <div
                      className="relative overflow-hidden rounded-lg cursor-pointer group ring-1 ring-slate-200"
                      onClick={() => setZoomUrl(f.frame_url)}
                    >
                      <img
                        src={f.frame_url}
                        alt={f.frame_name}
                        loading="lazy"
                        className="w-full aspect-[16/9] object-cover transition-transform duration-200 group-hover:scale-105"
                      />
                    </div>
                  )}
                  <div className="pointer-events-none absolute bottom-0 inset-x-0 bg-black/60 text-[11px] text-white text-center py-0.5 rounded-b-lg">
                    {stripName(f.frame_name)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Zoom 1 frame */}
      {zoomUrl && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/90"
          onClick={(e) => {
            e.stopPropagation();
            setZoomUrl(null);
          }}
        >
          <img src={zoomUrl} alt="Zoom" className="max-w-[95vw] max-h-[95vh] rounded shadow-lg" />
        </div>
      )}
    </div>
  );
}

export default FrameSequenceModal;
