// src/components/DuplicateGroupModal.jsx
// Bung MỘT cụm frame trùng thị giác: ô đại diện + các bản đã bị gộp khỏi lưới
// (backend/services/dedup_service). Không gọi mạng — bản trùng đã nằm sẵn trong
// SearchResult.duplicates của chính ô vừa bấm.
//
// Vì sao cần xem: các bản trùng thường là CÙNG một đoạn phát lại ở những video
// khác nhau. Nộp bài phải nộp đúng video, nên phải nhìn được cả cụm rồi chọn,
// chứ không thể tin ô đại diện chỉ vì nó điểm cao nhất.
import { useState } from 'react';
import ResultItem from './ResultItem';
import { CloseIcon } from './Icons';

const COL_LEVELS = [2, 3, 4, 5, 6, 8];

function DuplicateGroupModal({ group, onClose, onVideoClick, onFramesClick, basket, isSeen }) {
  const [cols, setCols] = useState(4);
  const [zoomUrl, setZoomUrl] = useState(null);

  // Đại diện đứng đầu, gắn cờ để phân biệt với bản trùng.
  const frames = [
    { ...group, _rep: true },
    ...(group.duplicates || []).map((d) => ({ ...d, _rep: false })),
  ];
  const videos = new Set(frames.map((f) => f.video_name));

  return (
    <div className="fixed inset-0 bg-slate-900/70 flex items-center justify-center z-[95] p-4" onClick={onClose}>
      <div
        className="bg-white rounded-xl shadow-2xl w-full max-w-7xl max-h-[92vh] flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="p-3 border-b border-slate-200 flex justify-between items-center">
          <div className="flex items-baseline space-x-3">
            <span className="text-slate-800 font-semibold text-lg">{frames.length} frame trùng nhau</span>
            <span className="text-sm text-slate-400">
              {videos.size} video · đại diện {group.video_name}
            </span>
          </div>
          <div className="flex items-center space-x-3">
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
            <button onClick={onClose} className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100">
              <CloseIcon className="w-5 h-5" />
            </button>
          </div>
        </div>

        <div className="p-4 overflow-y-auto">
          <p className="mb-3 text-xs text-slate-400">
            Chỉ ô đại diện được BLIP chấm lại; bản trùng giữ điểm retrieve nên đừng so
            điểm giữa hai loại. Thêm vào giỏ / mở video hoạt động bình thường ở mọi ô.
          </p>
          <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
            {frames.map((f) => (
              <div key={f.id} className={`relative rounded-lg ${f._rep ? 'ring-2 ring-indigo-500 ring-offset-1' : ''}`}>
                <ResultItem
                  result={{ ...f, duplicate_count: 0 }}
                  onImageClick={(r) => setZoomUrl(r.frame_url)}
                  onVideoClick={(r) => onVideoClick?.(r)}
                  onFramesClick={onFramesClick ? (r) => onFramesClick(r) : null}
                  basketRank={basket?.rankOf(f.id) ?? null}
                  basketQuestion={basket?.questionOf(f.id) ?? null}
                  currentQuestion={basket?.current}
                  onToggleBasket={basket ? basket.toggle : undefined}
                  seen={isSeen?.(f.id)}
                />
                <div className="pointer-events-none absolute bottom-0 inset-x-0 bg-black/60 text-[11px] text-white text-center py-0.5 rounded-b-lg">
                  {f.video_name} · {String(f.frame_name ?? '').replace(/\.webp$/i, '')}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

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

export default DuplicateGroupModal;
