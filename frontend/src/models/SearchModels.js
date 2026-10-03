// Dữ liệu backend trả về cho một kết quả
export class SearchResult {
  constructor({ id, score, frame_name, video_name, timestamp_ms, frame_url, video_url }) {
    this.id = id;
    this.score = score;
    this.frame_name = frame_name;
    this.video_name = video_name;
    this.timestamp_ms = timestamp_ms;
    this.frame_url = frame_url;
    this.video_url = video_url;
  }
}

// Dữ liệu query gửi lên backend
export class SearchQuery {
  constructor({ mode, text, temporal, image, k, ocrFilter, asrFilter }) {
    this.mode = mode;           // "text" | "temporal" | "image"
    this.text = text || "";
    this.temporal = temporal || "";
    this.image = image || null; // File hoặc base64
    this.k = k || 50;
    this.ocrFilter = ocrFilter || "";
    this.asrFilter = asrFilter || "";
  }
}
