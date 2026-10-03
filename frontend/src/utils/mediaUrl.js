// src/utils/mediaUrl.js
//
// Backend build frame_url/video_url từ MEDIA_BASE_URL (xem backend/config.py).
// Khi backend chạy trên Colab, MEDIA_BASE_URL phải là URL ngrok của frontend
// thì backend mới fetch được bytes ảnh cho rerank/agent vision. Nhưng trình
// duyệt lại chạy NGAY TRÊN máy đang giữ 11GB keyframe: nếu dùng nguyên URL đó
// thì mỗi thumbnail phải đi vòng browser -> ngrok edge -> ngrok agent -> Vite,
// tức một vòng WAN cho file nằm cách 2cm trên ổ đĩa.
//
// Hàm này giữ nguyên phần đường dẫn "/media/..." nhưng đổi host về origin đang
// mở app. Mở app ở localhost:5173 -> ảnh đọc thẳng từ disk. Mở qua ngrok ->
// origin chính là ngrok nên hành vi không đổi so với trước.

const MEDIA_MARKER = '/media/';

export function localizeMediaUrl(url) {
  if (typeof url !== 'string' || !url) return url;
  const idx = url.indexOf(MEDIA_MARKER);
  if (idx === -1) return url;
  // Chỉ viết lại URL tuyệt đối; đường dẫn tương đối vốn đã đúng origin.
  if (!/^https?:\/\//i.test(url)) return url;
  return window.location.origin + url.slice(idx);
}

const MEDIA_KEYS = new Set(['frame_url', 'video_url', 'thumbnail_url', 'image_url']);

/** Duyệt đệ quy payload JSON và localize mọi field URL media. */
export function localizeMediaUrlsDeep(data) {
  if (Array.isArray(data)) {
    for (const item of data) localizeMediaUrlsDeep(item);
    return data;
  }
  if (data && typeof data === 'object') {
    for (const [key, value] of Object.entries(data)) {
      if (typeof value === 'string') {
        if (MEDIA_KEYS.has(key)) data[key] = localizeMediaUrl(value);
      } else {
        localizeMediaUrlsDeep(value);
      }
    }
  }
  return data;
}
