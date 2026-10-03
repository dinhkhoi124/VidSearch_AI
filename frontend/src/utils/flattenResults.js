// src/utils/flattenResults.js
// Backend trả kết quả theo BA hình dạng khác nhau (xem backend/models/schemas.py):
//   grid      -> [SearchResult]                        : text/image/ocr/caption/feedback/agent
//   grouped   -> [{video_name, segments:[{asr_text, frames:[AsrFrame]}]}]      : /search_asr
//   temporal  -> [{video_name, best_sequence:{total_score, events:[TemporalEvent]}}]
//
// Cả ba đều mang đủ id/score/frame_name/timestamp_ms/fps/frame_url/video_url -
// chỉ AsrFrame và TemporalEvent thiếu `video_name` (nằm ở cấp videoGroup).
// Làm phẳng về MỘT danh sách để lưới, bộ lọc, gallery và phím tắt dùng chung
// một nguồn duy nhất, thay vì mỗi chế độ một đường.

// Ghi chú hiển thị kèm theo frame, dùng làm mô tả trong gallery.
const asrEntry = (frame, videoName, asrText) => ({
  ...frame,
  video_name: videoName,
  asr_text: asrText || "",
});

const temporalEntry = (event, videoName, totalScore) => ({
  ...event,
  video_name: videoName,
  total_score: totalScore,
});

export function flattenResults(results, resultType) {
  const list = Array.isArray(results) ? results : [];

  if (resultType === "grouped") {
    return list.flatMap((group) =>
      (group?.segments || []).flatMap((segment) =>
        (segment?.frames || []).map((frame) =>
          asrEntry(frame, group.video_name, segment.asr_text)
        )
      )
    );
  }

  if (resultType === "temporal") {
    return list.flatMap((group) =>
      (group?.best_sequence?.events || []).map((event) =>
        temporalEntry(event, group.video_name, group.best_sequence.total_score)
      )
    );
  }

  return list;
}
