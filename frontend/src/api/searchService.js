// src/api/searchService.js
import apiClient, { AGENT_TIMEOUT_MS } from "./apiClient";
import { SearchResult } from "../models/SearchModels";

/**
 * Gửi yêu cầu tìm kiếm bằng văn bản.
 * @param {string} query - Chuỗi văn bản tìm kiếm.
 * @param {number} k - Số lượng kết quả.
 * @param {string} model - Tên model.
 * @returns {Promise<SearchResult[]>}
 */
export async function searchText(query, k, model) {
  const params = { query, top_k: k, model };
  const response = await apiClient.post("/search_text", null, { params });
  
  // Ánh xạ kết quả trả về thành các đối tượng SearchResult
  return response.data.results.map(r => new SearchResult(r));
}

/**
 * Gửi yêu cầu tìm kiếm bằng hình ảnh.
 * @param {File} imageFile - File hình ảnh.
 * @param {number} k - Số lượng kết quả.
 * @param {string} model - Tên model.
 * @returns {Promise<SearchResult[]>}
 */
export async function searchImage(imageFile, k, model) {
  const formData = new FormData();
  formData.append("image", imageFile);

  const params = { top_k: k, model };

  const response = await apiClient.post("/search_image", formData, {
    params,
    headers: { "Content-Type": "multipart/form-data" },
  });

  return response.data.results.map(r => new SearchResult(r));
}

/**
 * Agent hội thoại: gửi TOÀN BỘ lịch sử chat, backend (Gemini) gộp thành một
 * structured plan rồi tự thực thi search/temporal.
 * @param {{role: string, content: string}[]} messages
 * @returns {Promise<{reply: string, plan: object, results: [], videos: []}>}
 */
export async function agentChat(messages, topK, model, rerank = false, deep = false) {
  const response = await apiClient.post("/agent/chat", {
    messages, top_k: topK, model, rerank, deep,
  }, { timeout: AGENT_TIMEOUT_MS });
  return response.data;
}

/**
 * Một cửa cho cả ba dạng đề: backend nhận dạng kis / qa / trake rồi tự gọi
 * đúng đường xử lý (xem backend/routers/agent.py::agent_ask). Ba pipeline vẫn
 * tách riêng - chỉ lối vào là chung.
 * @param {{role: string, content: string}[]} messages
 * @param {object} opts
 * @param {string} opts.taskType - "kis"|"qa"|"trake" khi đã biết dạng từ bộ đề;
 *                                 "" = để backend tự nhận dạng.
 * @param {string[]|null} opts.frameIds - QA: frame người dùng đã chọn sẵn.
 * @returns {Promise<{task_type: string, task_source: string, task_reason: string,
 *                    num_events: number, reply: string, answer: string,
 *                    plan: object, results: [], videos: [], trace: []}>}
 */
export async function agentAsk(messages, { taskType = "", frameIds = null, topK, model,
                                           rerank = false, deep = false } = {}) {
  const response = await apiClient.post("/agent/ask", {
    messages,
    task_type: taskType,
    frame_ids: frameIds && frameIds.length ? frameIds : null,
    top_k: topK, model, rerank, deep,
  }, { timeout: AGENT_TIMEOUT_MS });
  return response.data;
}

/**
 * Hỏi đáp RAG: frame ứng viên (ảnh + OCR/ASR của cảnh) được gửi cho Gemini vision.
 * @param {string} question
 * @param {string[]|null} frameIds - null/[] = backend tự retrieve từ câu hỏi
 * @returns {Promise<{answer: string, frames: []}>}
 */
export async function agentQa(question, frameIds, model) {
  const response = await apiClient.post("/agent/qa", {
    question,
    frame_ids: frameIds && frameIds.length ? frameIds : null,
    model,
  }, { timeout: AGENT_TIMEOUT_MS });
  return response.data;
}

/**
 * Backbone visual mà BACKEND ĐANG CHẠY dùng được (có index trên đĩa của nó),
 * kèm cấu hình ensemble. UI dựng ô chọn model từ đây thay vì hardcode.
 * @returns {Promise<{default: string, ensemble: object, models: object[]}>}
 */
export async function getModels() {
  const response = await apiClient.get("/models");
  return response.data;
}

/**
 * Trạng thái hạn mức của key LLM (Gemini / endpoint OpenAI-compat).
 * Dùng lúc mở trang và khi người dùng bấm "Kiểm tra lại" — giữa chừng thì
 * header của mọi response đã tự cập nhật (xem api/llmStatus.js).
 * @returns {Promise<{exhausted: boolean, provider?: string, scope?: string}>}
 */
export async function getLlmStatus() {
  const response = await apiClient.get("/agent/llm_status");
  return response.data;
}

/**
 * Dán key Gemini mới cho backend đang chạy (key cũ cạn quota giữa buổi thi).
 * Backend thử key trước khi nhận, và chỉ giữ trong RAM.
 * @param {string} apiKey
 * @param {string} model - rỗng = giữ model hiện tại
 * @returns {Promise<{ok: boolean, key_hint: string, model: string, message: string}>}
 */
export async function setGeminiKey(apiKey, model = "") {
  const response = await apiClient.post("/agent/llm_key", {
    api_key: apiKey, provider: "gemini", model,
  }, { timeout: 30000 });
  return response.data;
}

/**
 * Cấu hình LLM đang chạy ở backend (key đã che, chỉ 4 ký tự cuối).
 * Không gọi mạng phía backend nên gọi mỗi lần mở Cài đặt là rẻ.
 * @returns {Promise<{provider: string, providers: string[], can_edit: boolean,
 *   gemini: {configured: boolean, key_hint: string, model: string},
 *   openai: {configured: boolean, base_url: string, host: string, key_hint: string,
 *            model: string, react_model: string, qa_model: string,
 *            effective_react: string, effective_qa: string, max_tokens: number}}>}
 */
export async function getLlmConfig() {
  const response = await apiClient.get("/agent/llm_config");
  return response.data;
}

/**
 * Đổi provider / model / endpoint OpenAI-compat mà không restart backend.
 * CHỈ gửi những field thực sự đổi: field vắng mặt = giữ nguyên, còn chuỗi rỗng
 * = xoá (react/qa rỗng nghĩa là dùng lại openai_model).
 * @param {{provider?: string, openai_model?: string, openai_react_model?: string,
 *          openai_qa_model?: string, openai_base_url?: string, openai_api_key?: string}} patch
 * @returns {Promise<{ok: boolean, message: string, config: object}>}
 */
export async function setLlmConfig(patch) {
  const response = await apiClient.post("/agent/llm_config", patch, { timeout: 30000 });
  return response.data;
}

/**
 * Relevance feedback: trộn embedding các frame người dùng chọn với query gốc
 * (MemoriEase 3.0 §3.5) rồi search lại. Frame đã chọn bị loại khỏi kết quả.
 * @param {string[]} frameIds
 * @returns {Promise<SearchResult[]>}
 */
export async function searchFeedback(frameIds, query, topK, model) {
  const response = await apiClient.post("/search_feedback", {
    frame_ids: frameIds, query, top_k: topK, model,
  });
  return response.data.results;
}
/**
 * Kiểm chứng giỏ đáp án trước khi nộp: backend đối chiếu từng (video, frame)
 * với bằng chứng ASR/OCR/caption trong index (xem backend routers/verify.py).
 * @param {{qid:number, task_type:string, query_text:string,
 *          rows:{video_name:string, frames:number[], answer:string}[]}[]} questions
 * @returns {Promise<{reports: {qid:number, warnings:{level:string,msg:string}[]}[]}>}
 */
export async function verifyAnswers(questions) {
  const response = await apiClient.post("/verify_answers", { questions },
    { timeout: 120000 });
  return response.data;
}
