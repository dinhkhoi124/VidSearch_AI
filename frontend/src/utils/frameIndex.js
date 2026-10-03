// src/utils/frameIndex.js
// Tính frame_idx (chỉ số frame trong VIDEO GỐC) để nộp bài AIC.
//
// Quy ước: tên keyframe (vd "000123.webp") chính là chỉ số frame gốc do bước
// extract sinh ra -> parse tên frame là nguồn chuẩn. Nếu tên không phải số
// (thiếu/format lạ) thì fallback round(timestamp_ms/1000 * fps) - cùng công
// thức VideoPlayerModal đang dùng để hiển thị "Current Frame Index".

export function parseFrameNumber(frameName) {
  if (frameName == null) return null;
  // Neo vào phần stem của tên file, KHÔNG bắt cụm số đầu tiên gặp được: với
  // "L01_V028/000125.webp" thì /(\d+)/ trả về 1 - một frame_idx trông hợp lệ,
  // sai hoàn toàn, và không validator nào bắt được.
  const base = String(frameName).split(/[\\/]/).pop();
  const stem = base.replace(/\.[^.]+$/, "");
  return /^\d+$/.test(stem) ? parseInt(stem, 10) : null;
}

export function frameIndex(result) {
  if (!result) return null;
  const parsed = parseFrameNumber(result.frame_name);
  if (parsed != null) return parsed;

  const { timestamp_ms, fps } = result;
  if (timestamp_ms != null && fps) {
    return Math.round((timestamp_ms / 1000) * fps);
  }
  return null;
}

// Chỉ số suy ra từ timestamp - dùng để đối chiếu/verify với parseFrameNumber.
export function frameIndexFromTime(result) {
  if (!result || result.timestamp_ms == null || !result.fps) return null;
  return Math.round((result.timestamp_ms / 1000) * result.fps);
}

// Khoảng shot chứa frame -> "02:12 → 02:19 (7.0s)", hoặc "" khi backend chưa
// có graph.json. Biết shot dài bao nhiêu giúp quyết định keyframe có nằm đúng
// cảnh của sự kiện không - thứ mà mốc mm:ss đơn lẻ không nói được.
export function fmtShot(result) {
  const a = result?.shot_start_ms;
  const b = result?.shot_end_ms;
  if (a == null || b == null) return "";
  const dur = ((b - a) / 1000).toFixed(1);
  return `${fmtTime(a)} → ${fmtTime(b)} (${dur}s)`;
}

// timestamp_ms -> "mm:ss" (hoặc "h:mm:ss" khi video dài hơn 1 tiếng).
// Dùng để nói cho người dùng biết frame đang xem nằm ở đoạn nào của video.
export function fmtTime(ms) {
  if (ms == null || Number.isNaN(Number(ms))) return "--:--";
  const total = Math.max(0, Math.floor(Number(ms) / 1000));
  const s = total % 60;
  const m = Math.floor(total / 60) % 60;
  const h = Math.floor(total / 3600);
  const pad = (n) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}
