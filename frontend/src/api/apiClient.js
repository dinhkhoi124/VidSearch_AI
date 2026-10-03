// src/api/apiClient.js
import axios from "axios";
import { localizeMediaUrlsDeep } from "../utils/mediaUrl";
import { applyLlmHeaders } from "./llmStatus";

// Thứ tự ưu tiên base URL của backend:
//   1. localStorage "aic.apiBase"  -> đổi runtime trong Settings, không cần rebuild
//   2. import.meta.env.VITE_API_BASE_URL -> cấu hình lúc build (frontend/.env)
//   3. suy ra từ host đang mở FE -> mặc định
const BACKEND_PORT = 8000;

// Khi thi 5 người: MỘT máy chạy cả BE (8000) lẫn FE (5173), đồng đội mở
// http://<IP-máy-chủ>:5173. Suy base URL từ chính host đó thay vì hardcode
// localhost, nếu không 4 máy kia sẽ gọi vào backend của CHÍNH NÓ (không có).
// Cách này cũng khỏi phải sửa .env mỗi lần IP phòng thi đổi.
export function defaultBaseUrl() {
  if (typeof window === "undefined") return `http://localhost:${BACKEND_PORT}`;
  const { protocol, hostname } = window.location;
  // file:// hoặc host rỗng -> không suy được, quay về localhost.
  if (!hostname) return `http://localhost:${BACKEND_PORT}`;
  const scheme = protocol === "https:" ? "https:" : "http:";
  return `${scheme}//${hostname}:${BACKEND_PORT}`;
}

export function resolveBaseUrl() {
  try {
    const stored = localStorage.getItem("aic.apiBase");
    if (stored) return JSON.parse(stored);
  } catch {
    // localStorage bị chặn -> bỏ qua
  }
  return import.meta.env.VITE_API_BASE_URL || defaultBaseUrl();
}

// ngrok free chèn một trang HTML "You are about to visit..." cho mọi request có
// User-Agent trình duyệt - XHR cũng mang UA trình duyệt, nên KHÔNG có header này
// thì mọi lời gọi API qua tunnel nhận về HTML kèm status 200 thay vì JSON, và
// lỗi hiện ra là lỗi parse khó hiểu chứ không phải lỗi mạng. Giá trị nào cũng
// được; vô hại khi không dùng ngrok nên đặt cố định.
export const TUNNEL_HEADERS = { "ngrok-skip-browser-warning": "true" };

// Các endpoint gọi LLM (/agent/chat, /agent/qa) KHÔNG vừa timeout mặc định:
// một lượt là plan (1 call Gemini) + fan-out 3-5 kênh + neighbor/scene
// aggregation + rerank BLIP, và có thể leo ReAct tối đa 3 vòng — mỗi vòng lại
// một call LLM. Riêng QA vision (12 ảnh) backend đã cho 120s cho MỘT call.
// Cộng độ trễ ngrok thì 60s cắt ngang giữa chừng: người dùng thấy "timeout"
// trong khi backend vẫn đang chạy tiếp và tính tiền quota.
export const AGENT_TIMEOUT_MS = 300000;

const apiClient = axios.create({
  baseURL: resolveBaseUrl(),
  // Không có timeout thì backend treo = spinner quay vĩnh viễn, không có cách
  // nào biết là hỏng. 120s cho truy vấn thường (temporal nặng nhất + expansion
  // qua LLM + rerank, đi qua tunnel); lời gọi agent tự nâng lên AGENT_TIMEOUT_MS.
  timeout: 120000,
  headers: {
    "Content-Type": "application/json",
    ...TUNNEL_HEADERS,
  },
});

// Backend build frame_url/video_url theo MEDIA_BASE_URL của nó (URL ngrok của
// FE khi backend chạy trên Colab). Trình duyệt thì đang ngồi cùng máy với kho
// media, nên viết lại host về origin hiện tại để ảnh không phải đi vòng qua
// tunnel. Xem utils/mediaUrl.js.
apiClient.interceptors.response.use((response) => {
  localizeMediaUrlsDeep(response.data);
  applyLlmHeaders(response.headers);
  return response;
});

// Trạng thái quota cũng phải bắt ở nhánh LỖI: request hỏng (503 thiếu index,
// 500 của agent) vẫn mang header, và đó chính là lúc người dùng cần biết key
// Gemini đã hết lượt. Ném lại nguyên lỗi để mọi caller xử lý như cũ.
apiClient.interceptors.response.use(undefined, (error) => {
  if (error?.response?.headers) applyLlmHeaders(error.response.headers);
  return Promise.reject(error);
});

// Ai cần biết base URL vừa đổi. roomClient giữ kết nối WebSocket riêng, không đi
// qua axios, nên nếu không báo thì nó bám host cũ tới lúc F5 - đúng thao tác làm
// mỗi buổi ngrok vì URL tunnel đổi theo session.
const baseUrlListeners = new Set();

export function subscribeBaseUrl(fn) {
  baseUrlListeners.add(fn);
  return () => baseUrlListeners.delete(fn);
}

// Cho phép Settings đổi base URL runtime; lưu vào localStorage để sống qua refresh.
export function setApiBaseUrl(url) {
  const clean = (url || "").trim() || defaultBaseUrl();
  const changed = apiClient.defaults.baseURL !== clean;
  apiClient.defaults.baseURL = clean;
  try {
    localStorage.setItem("aic.apiBase", JSON.stringify(clean));
  } catch {
    // bỏ qua
  }
  // Chỉ báo khi thực sự đổi: bấm "Lưu" mà không sửa gì thì không nên đá phòng
  // ra rồi nối lại.
  if (changed) baseUrlListeners.forEach((fn) => fn(clean));
  return clean;
}

export default apiClient;
