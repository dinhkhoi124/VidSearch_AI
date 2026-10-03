// src/components/AsrResultGroup.jsx
// Trình bày riêng cho kết quả ASR (gom theo video -> segment lời thoại), nhưng
// HÀNH VI của mỗi ô giống hệt lưới chính: cùng ResultItem, cùng gallery, cùng
// nút Thêm/Xem video/Chuỗi frame, cùng dấu "đã xem".
import ResultItem from './ResultItem';

function AsrResultGroup({
  videoGroup,
  resolve,          // id -> object đã chuẩn hoá trong danh sách phẳng (xem utils/flattenResults.js)
  onVideoClick,
  onImageClick,
  onFramesClick,
  basketRankOf,
  basketQuestionOf,
  currentQuestion,
  onToggleBasket,
  focusedId,
  focusedRef,       // gắn vào ô đang focus để SearchPage cuộn tới được
  isSeen,
}) {
  return (
    <div className="col-span-full mb-6">
      {/* Tiêu đề cho mỗi video */}
      <h2 className="text-lg font-bold text-slate-900 mb-3">{videoGroup.video_name}</h2>

      {/* Lặp qua từng phân đoạn (segment) */}
      {videoGroup.segments.map((segment, index) => (
        <div key={index} className="mb-4 pl-4 border-l-2 border-slate-300">
          {/* Lời thoại của segment */}
          <p className="text-sm text-slate-600 italic mb-2">{segment.asr_text}</p>

          {/* Lưới hiển thị các frame của segment */}
          <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 xl:grid-cols-8 gap-2">
            {segment.frames.map((frame) => {
              // Lấy CHÍNH object mà lưới/gallery/giỏ đang dùng - tham chiếu ổn
              // định nên memo(ResultItem) còn tác dụng, và tra index trong
              // gallery không lệch. Frame bị bộ lọc loại thì bỏ qua.
              const result = resolve(frame.id);
              if (!result) return null;
              const focused = focusedId === frame.id;
              return (
                <div key={frame.id} ref={focused ? focusedRef : null}>
                  <ResultItem
                    result={result}
                    onVideoClick={onVideoClick}
                    onImageClick={onImageClick}
                    onFramesClick={onFramesClick}
                    basketRank={basketRankOf ? basketRankOf(frame.id) : null}
                    basketQuestion={basketQuestionOf ? basketQuestionOf(frame.id) : null}
                    currentQuestion={currentQuestion}
                    onToggleBasket={onToggleBasket}
                    focused={focused}
                    seen={isSeen ? isSeen(frame.id) : false}
                  />
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

export default AsrResultGroup;
