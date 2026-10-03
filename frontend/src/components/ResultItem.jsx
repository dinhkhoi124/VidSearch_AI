// src/components/ResultItem.jsx

import { memo } from 'react';
import { LazyLoadImage } from 'react-lazy-load-image-component';
import 'react-lazy-load-image-component/src/effects/blur.css';
import { PlayIcon, FilmIcon, PlusIcon } from './Icons';

function ResultItem({
  result,
  onVideoClick,
  onImageClick,
  onFramesClick,
  basketRank, // hạng trong giỏ của CÂU HIỆN TẠI (null nếu chưa thêm)
  basketQuestion, // câu khác đang chứa frame này (null nếu không có)
  currentQuestion, // số câu đang trả lời - chỉ để hiển thị tooltip
  onToggleBasket,
  focused, // ô đang được chọn (đồng bộ với ảnh đang mở trong gallery)
  seen, // đã xem (mở video/zoom) -> làm mờ nhẹ
  onDupesClick, // bấm badge ×N -> mở cụm frame trùng đã bị gộp
}) {
  if (!result || !result.frame_url) {
    return null;
  }

  const inBasket = basketRank != null;
  // Frame đã nằm ở giỏ của câu khác -> cảnh báo để tránh nộp trùng.
  const inOtherQuestion = !inBasket && basketQuestion != null;

  const handleVideoIconClick = (e) => {
    e.stopPropagation();
    onVideoClick(result);
  };

  const handleBasketClick = (e) => {
    e.stopPropagation();
    if (onToggleBasket) onToggleBasket(result);
  };

  const handleFramesIconClick = (e) => {
    e.stopPropagation();
    if (onFramesClick) onFramesClick(result);
    else if (onImageClick) onImageClick(result);
  };

  const score = typeof result.score === 'number' ? result.score : null;

  const basketTitle = inBasket
    ? `Đang ở giỏ câu ${currentQuestion ?? ''} (hạng ${basketRank}) - bấm để bỏ`
    : inOtherQuestion
    ? `Frame này đã dùng cho câu ${basketQuestion} - bấm để thêm vào câu ${currentQuestion ?? ''}`
    : `Thêm vào giỏ đáp án câu ${currentQuestion ?? ''}`;

  return (
    <div
      className={`relative aspect-[16/9] rounded-lg overflow-hidden group bg-slate-200 cursor-pointer border transition-shadow hover:shadow-md ${
        inBasket
          ? 'border-emerald-500 ring-2 ring-emerald-500/30'
          : inOtherQuestion
          ? 'border-amber-400 ring-1 ring-amber-400/40'
          : 'border-slate-200'
      } ${focused ? 'outline-2 outline-amber-400 outline-offset-2' : ''}`}
      onClick={() => (onImageClick ? onImageClick(result) : onVideoClick(result))}
    >
      {/* Badge điểm số */}
      {score != null && (
        <span className="absolute top-1.5 left-1.5 z-10 bg-slate-900/70 text-white text-[11px] font-semibold px-1.5 py-0.5 rounded backdrop-blur-sm tabular-nums">
          {score.toFixed(3)}
        </span>
      )}

      {/* Số frame trùng thị giác đã gộp vào ô này — bấm để xem cả cụm */}
      {result.duplicate_count > 0 && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDupesClick?.(result);
          }}
          disabled={!onDupesClick}
          className="absolute top-1.5 right-1.5 z-10 bg-indigo-600/85 hover:bg-indigo-600 text-white text-[11px] font-semibold px-1.5 py-0.5 rounded backdrop-blur-sm tabular-nums transition-colors"
          title={`Đã gộp ${result.duplicate_count} frame trùng thị giác — bấm để xem cả cụm`}
        >
          ×{result.duplicate_count + 1}
        </button>
      )}

      {/* Nút thêm vào giỏ đáp án của câu hiện tại */}
      {onToggleBasket && (
        <button
          onClick={handleBasketClick}
          title={basketTitle}
          className={`absolute bottom-1.5 left-1.5 z-10 min-w-7 h-7 px-1.5 rounded-full flex items-center justify-center text-xs font-bold shadow-sm transition-all ${
            inBasket
              ? 'bg-emerald-500 text-white opacity-100'
              : inOtherQuestion
              ? 'bg-amber-400 text-slate-900 opacity-100'
              : 'bg-white/90 text-slate-700 hover:bg-white opacity-0 group-hover:opacity-100'
          }`}
        >
          {inBasket ? `#${basketRank}` : inOtherQuestion ? `C${basketQuestion}` : <PlusIcon className="w-4 h-4" />}
        </button>
      )}

      <LazyLoadImage
        alt={result.frame_name || 'Search result'}
        src={result.frame_url}
        effect="blur"
        className={`w-full h-full object-cover transition-transform duration-300 group-hover:scale-105 ${
          seen ? 'opacity-60' : ''
        }`}
        // KHÔNG đặt placeholderSrc trỏ ra host ngoài: với top-K 200–1000 ô thì
        // mỗi ô là một request bên thứ ba, và trên mạng hội trường bị chặn sẽ
        // treo hết một vòng DNS/TCP rồi hiện ảnh vỡ. Nền bg-slate-200 của thẻ
        // bọc đã đủ làm chỗ giữ chỗ.
        decoding="async"
      />

      {/* Đã xem: chỉ làm mờ ảnh (xem class ở LazyLoadImage trên). Trước đây có
          thêm huy hiệu con mắt ở góc phải dưới, nhưng nó đè đúng chỗ nút "chuỗi
          frame" lúc hover mà không nói thêm gì so với việc ô đã bị mờ. */}

      {/* Overlay khi hover */}
      <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent flex flex-col justify-between p-2 opacity-0 group-hover:opacity-100 transition-opacity duration-300">
        <div className="text-white text-xs font-semibold break-words pl-12 drop-shadow">
          {result.video_name},{String(result.frame_name ?? '').replace(/\.webp$/i, '')}
        </div>
        <div className="flex justify-between items-end">
          <button onClick={handleVideoIconClick} title="Mở video" className="text-white hover:text-blue-300 transition-colors">
            <PlayIcon className="w-7 h-7" />
          </button>
          <button onClick={handleFramesIconClick} title="Xem các frame liên tiếp" className="text-white hover:text-blue-300 transition-colors">
            <FilmIcon className="w-7 h-7" />
          </button>
        </div>
      </div>
    </div>
  );
}

// memo: chỉ re-render khi props của ĐÚNG ô này đổi (giỏ/đã xem/focus).
// Nhờ vậy khi thao tác trên lưới lớn, không re-render cả nghìn ô.
export default memo(ResultItem);
