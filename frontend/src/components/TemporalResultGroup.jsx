// src/components/TemporalResultGroup.jsx
// Trình bày riêng cho kết quả temporal (chuỗi sự kiện nối tiếp trong một video),
// nhưng HÀNH VI mỗi ô giống hệt lưới chính - xem ghi chú ở AsrResultGroup.
import ResultItem from './ResultItem';

// Bảng màu cho các sự kiện khác nhau - phải đủ 4 màu vì tìm kiếm temporal cho
// tới 4 event (MAX_TEMPORAL_EVENTS); trước đây chỉ có 3 nên event 1 và event 4
// lấy trùng màu đỏ, nhìn tưởng cùng một sự kiện.
const eventColors = ['border-red-500', 'border-blue-500', 'border-green-500', 'border-violet-500'];

function TemporalResultGroup({
  videoGroup,
  resolve,
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
  const { video_name, best_sequence } = videoGroup;
  // Không có error boundary trong cây, nên một field thiếu ở payload là trắng
  // cả app giữa lúc thi - đọc phòng thủ thay vì tin backend luôn đủ field.
  const totalScore = best_sequence?.total_score;
  const events = best_sequence?.events || [];

  return (
    <div className="col-span-full mb-8">
      <div className="flex justify-between items-center mb-3">
        <h2 className="text-lg font-bold text-slate-900">{video_name}</h2>
        <span className="text-sm font-semibold text-amber-600 tabular-nums">
          Total Score: {typeof totalScore === 'number' ? totalScore.toFixed(4) : '-'}
        </span>
      </div>

      {/* Hiển thị chuỗi các frame sự kiện */}
      <div className="flex items-center space-x-6 p-6 bg-white border border-slate-200 rounded-xl overflow-x-auto">
        {events.map((event, i) => {
          const result = resolve(event.id);
          if (!result) return null;
          const focused = focusedId === event.id;
          // event_index thiếu -> NaN -> eventColors[NaN] là undefined và viền
          // biến mất; rơi về thứ tự hiển thị để mỗi event vẫn có màu riêng.
          const colorIdx = Number.isInteger(event.event_index) ? event.event_index : i;
          return (
            <div
              key={event.id}
              ref={focused ? focusedRef : null}
              className={`flex-shrink-0 w-64 h-40 border-2 ${eventColors[colorIdx % eventColors.length]} rounded-lg`}
            >
              <ResultItem
                result={result}
                onVideoClick={onVideoClick}
                onImageClick={onImageClick}
                onFramesClick={onFramesClick}
                basketRank={basketRankOf ? basketRankOf(event.id) : null}
                basketQuestion={basketQuestionOf ? basketQuestionOf(event.id) : null}
                currentQuestion={currentQuestion}
                onToggleBasket={onToggleBasket}
                focused={focused}
                seen={isSeen ? isSeen(event.id) : false}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default TemporalResultGroup;
