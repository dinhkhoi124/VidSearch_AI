// src/hooks/useSearch.js
import { useRef, useState } from "react";
import apiClient from "../api/apiClient";

export function useSearch() {
  const [results, setResults] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [resultType, setResultType] = useState('grid');
  // Đã chạy ít nhất một lần tìm kiếm chưa - để phân biệt "chưa tìm" với
  // "tìm rồi, không có kết quả nào".
  const [hasSearched, setHasSearched] = useState(false);
  // Bộ lọc caption gõ tiếng Việt được backend dịch sang tiếng Anh — giữ lại
  // để UI hiện đúng chữ đang lọc, nếu không "0 kết quả" là một hộp đen.
  const [captionTranslation, setCaptionTranslation] = useState("");

  // Mốc phiên: chỉ phản hồi của lần tìm MỚI NHẤT được phép ghi vào state. Không
  // có nó thì gõ hai truy vấn liên tiếp sẽ do phản hồi về sau thắng, kể cả khi
  // đó là kết quả của truy vấn cũ.
  const runIdRef = useRef(0);

  // Hàm để reset trạng thái từ bên ngoài
  const clearSearchState = () => {
    runIdRef.current += 1; // huỷ hiệu lực phản hồi đang bay
    setResults([]);
    setCaptionTranslation("");
    setError("");
    setResultType('grid');
    setHasSearched(false);
  };

  // Đổ kết quả từ bên ngoài (agent chat / relevance feedback) vào lưới chính
  const injectResults = (list, type = 'grid') => {
    runIdRef.current += 1;
    setResults(list || []);
    setResultType(type);
    setError("");
    setHasSearched(true);
  };

  const executeSearch = async (searchParams) => {
    const runId = (runIdRef.current += 1);
    const isStale = () => runIdRef.current !== runId;

    setResults([]);
    setError("");
    setCaptionTranslation("");
    setIsLoading(true);
    setResultType('grid');

    // Logic kiểm tra đầu vào
    try {
      const { mode, query, imageFile, temporalData } = searchParams;
      if ((mode === 'text' || mode === 'ocr' || mode === 'asr') && (!query || !query.trim())) {
        throw new Error("Please enter a search query.");
      }
      if (mode === 'image' && !imageFile) {
        throw new Error("Please upload an image to search.");
      }
      if (mode === 'temporal' && (!temporalData || !temporalData.events.some(e => e.query.trim()))) {
        throw new Error("Please enter a description for at least one event.");
      }
    } catch (err) {
      setError(err.message);
      setIsLoading(false);
      return;
    }

    try {
      let response;
      let list = [];
      const { mode, query, imageFile, k, model, temporalData, ocrFilter, asrFilter, captionFilter, textMode = "filter", rerank = true, expand = true, dedup = true, dedupThreshold = 0 } = searchParams;
      const baseParams = {
        query, top_k: k, model,
        ocr_keywords: ocrFilter, asr_keywords: asrFilter,
        // Chỉ /search_text đọc caption_keywords; /search_ocr bỏ qua tham số lạ.
        caption_keywords: captionFilter || "",
        // filter = cổng AND (mặc định), fuse = ba ô lọc thành kênh retrieval
        // riêng rồi cộng điểm với visual. /search_ocr bỏ qua tham số này.
        text_mode: textMode,
        rerank, expand,
        // Gộp frame trùng thị giác. 0 = để backend dùng RESULT_DEDUP_THRESHOLD.
        dedup, dedup_threshold: dedupThreshold,
      };

      if (mode === 'text' || mode === 'ocr') {
        const endpoint = mode === 'text' ? '/search_text' : '/search_ocr';
        response = await apiClient.post(endpoint, null, { params: baseParams });
        if (isStale()) return;
        list = response.data.results || [];
        setCaptionTranslation(response.data.caption_translation || "");
        setResults(list);
      } else if (mode === 'image') {
        const formData = new FormData();
        formData.append("image", imageFile);
        response = await apiClient.post("/search_image", formData, { params: { top_k: k, model, dedup, dedup_threshold: dedupThreshold }, headers: { "Content-Type": "multipart/form-data" } });
        if (isStale()) return;
        list = response.data.results || [];
        setResults(list);
      } else if (mode === 'asr') {
        response = await apiClient.post('/search_asr', null, { params: { query, asr_filter: asrFilter, rerank } });
        if (isStale()) return;
        list = response.data.videos || [];
        setResultType('grouped');
        setResults(list);
      } else if (mode === 'temporal') {
        // Backend nhận q1..q4 dạng phẳng và tự bỏ qua event rỗng, nên chỉ cần
        // trải mảng events (1..MAX_TEMPORAL_EVENTS) ra đúng chỉ số.
        const flatTemporalParams = {
          model: model,
          topk_per_event: temporalData.topk_per_event
        };
        temporalData.events.forEach((ev, i) => {
          flatTemporalParams[`q${i + 1}`] = ev.query;
          flatTemporalParams[`ocr${i + 1}`] = ev.ocr;
          flatTemporalParams[`asr${i + 1}`] = ev.asr;
        });
        response = await apiClient.post('/search_temporal', null, { params: flatTemporalParams });
        if (isStale()) return;
        list = response.data.videos || [];
        setResultType('temporal');
        setResults(list);
      }

      // Không đặt error khi rỗng: 0 kết quả là kết cục hợp lệ, không phải hỏng.
      // hasSearched để UI phân biệt "chưa tìm" với "tìm rồi, rỗng" - phép kiểm
      // tra cũ (!results && !videos) không bao giờ đúng vì mảng rỗng là truthy.
      setHasSearched(true);
    } catch (err) {
      if (isStale()) return;
      console.error("Search hook error:", err);
      setError(err.response?.data?.detail || err.message || "An error occurred.");
      setHasSearched(true);
    } finally {
      if (!isStale()) setIsLoading(false);
    }
  };

  return { results, isLoading, error, resultType, hasSearched, captionTranslation, executeSearch, clearSearchState, injectResults };
}