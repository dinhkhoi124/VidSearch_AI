// src/pages/SearchPage.jsx
import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import { useSearch } from "../hooks/useSearch";
import { usePersistedState } from "../hooks/usePersistedState";
import { useAnswerBasket } from "../hooks/useAnswerBasket";
import { useSeenFrames } from "../hooks/useSeenFrames";
import { useQueryHistory } from "../hooks/useQueryHistory";
import { useRoom } from "../hooks/useRoom";
import { useHotkeys, isEditableTarget } from "../hooks/useHotkeys";
import { flattenResults } from "../utils/flattenResults";

import ResultItem from '../components/ResultItem';
import ResultGallery from '../components/ResultGallery';
import VideoPlayerModal from '../components/VideoPlayerModal';
import FrameSequenceModal from '../components/FrameSequenceModal';
import DuplicateGroupModal from '../components/DuplicateGroupModal';
import AsrResultGroup from "../components/AsrResultGroup";
import TemporalResultGroup from "../components/TemporalResultGroup";
import AgentChatPanel from "../components/AgentChatPanel";
import SubmissionPanel from "../components/SubmissionPanel";
import SettingsModal from "../components/SettingsModal";
import HotkeysHelp from "../components/HotkeysHelp";
import QuestionSwitcher from "../components/QuestionSwitcher";
import MemberBar from "../components/MemberBar";
import RoomJoinModal from "../components/RoomJoinModal";
import LlmQuotaBanner from "../components/LlmQuotaBanner";
import { initials, memberColor } from "../utils/memberStyle";
import { searchFeedback } from "../api/searchService";
import { DEFAULT_VISUAL_MODEL, normalizeModel } from "../constants/models";
import { useVisualModels } from "../hooks/useVisualModels";
import {
  SearchIcon, InboxIcon, KeyboardIcon, SettingsIcon, ClockIcon,
  ChatIcon, UploadIcon, AicMark,
  TypeIcon, ImageIcon, MicIcon, MenuIcon, PlusIcon, TrashIcon, CheckIcon,
} from "../components/Icons";

// Lớp dùng chung
const field = "w-full px-3 py-2 bg-white border border-slate-300 rounded-lg text-sm text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500 transition";
const card = "bg-slate-50 border border-slate-200 rounded-lg p-3";
// Ô vuông 36px cố định thay vì để padding tự quyết: mọi thứ trong header
// (nút icon, viên thuốc phòng) cùng một chiều cao thì hàng mới thẳng.
const iconBtn =
  "inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-800";

const MODES = [
  { id: "text", label: "Text", Icon: SearchIcon },
  { id: "image", label: "Image", Icon: ImageIcon },
  { id: "ocr", label: "OCR", Icon: TypeIcon },
  { id: "asr", label: "ASR", Icon: MicIcon },
  { id: "temporal", label: "Temporal", Icon: ClockIcon },
];

// Backend /search_temporal chỉ nhận q1..q4 (xem routers/search_temporal.py).
const MAX_TEMPORAL_EVENTS = 4;
const emptyEvent = () => ({ query: "", ocr: "", asr: "" });

// Giao diện nhập liệu Temporal - bắt đầu 1 event, thêm/bớt tuỳ đề bài.
const TemporalInput = ({ temporalData, setTemporalData }) => {
  const events = temporalData.events;
  const handleInputChange = (e, index, f) => {
    const newEvents = events.map((ev, i) => (i === index ? { ...ev, [f]: e.target.value } : ev));
    setTemporalData({ ...temporalData, events: newEvents });
  };
  const addEvent = () => {
    if (events.length >= MAX_TEMPORAL_EVENTS) return;
    setTemporalData({ ...temporalData, events: [...events, emptyEvent()] });
  };
  const removeEvent = (index) => {
    if (events.length <= 1) return;
    setTemporalData({ ...temporalData, events: events.filter((_, i) => i !== index) });
  };
  const full = events.length >= MAX_TEMPORAL_EVENTS;
  return (
    <div className="space-y-3">
      {events.map((ev, i) => (
        <div key={i} className="p-3 bg-slate-50 border border-slate-200 rounded-lg space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-blue-600">Event {i + 1}</h3>
            {events.length > 1 && (
              <button onClick={() => removeEvent(i)} title="Xoá sự kiện này"
                className="p-1 rounded text-slate-400 hover:text-red-600 hover:bg-red-50 transition-colors">
                <TrashIcon className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
          <textarea className={`${field} h-20 resize-none`} placeholder={`Scene ${i + 1} description...`} value={ev.query} onChange={(e) => handleInputChange(e, i, 'query')} />
          <div className="grid grid-cols-2 gap-2">
            <input type="text" className={field} placeholder="OCR filter..." value={ev.ocr} onChange={(e) => handleInputChange(e, i, 'ocr')} />
            <input type="text" className={field} placeholder="ASR filter..." value={ev.asr} onChange={(e) => handleInputChange(e, i, 'asr')} />
          </div>
        </div>
      ))}
      <button onClick={addEvent} disabled={full}
        title={full ? `Tối đa ${MAX_TEMPORAL_EVENTS} sự kiện` : "Thêm một sự kiện nối tiếp"}
        className="w-full inline-flex items-center justify-center gap-1.5 py-2 border-2 border-dashed border-slate-300 rounded-lg text-sm font-semibold text-slate-500 hover:border-blue-400 hover:text-blue-600 hover:bg-blue-50/50 disabled:opacity-40 disabled:hover:border-slate-300 disabled:hover:text-slate-500 disabled:hover:bg-transparent disabled:cursor-not-allowed transition-colors">
        <PlusIcon className="w-4 h-4" /> {full ? `Tối đa ${MAX_TEMPORAL_EVENTS} sự kiện` : "Thêm sự kiện"}
      </button>
    </div>
  );
};


function SearchPage() {
  const { results, isLoading, error, resultType, hasSearched, captionTranslation, executeSearch, clearSearchState, injectResults } = useSearch();

  // --- UI State ---
  // Tab cấp cao của sidebar: form tìm kiếm thủ công hay khung chat Agent.
  const [panelTab, setPanelTab] = usePersistedState("aic.paneltab", "manual");
  const [mode, setMode] = usePersistedState("aic.mode", "text");
  const [k, setK] = usePersistedState("aic.topk", 200);
  const [textQuery, setTextQuery] = useState("");
  const [ocrQuery, setOcrQuery] = useState("");
  const [asrQuery, setAsrQuery] = useState("");
  const [imageFile, setImageFile] = useState(null);
  const [ocrFilter, setOcrFilter] = useState("");
  const [asrFilter, setAsrFilter] = useState("");
  // Lọc theo caption sinh sẵn (Qwen2.5-VL, tiếng Anh) — mọi từ phải có mặt.
  const [captionFilter, setCaptionFilter] = useState("");
  // Ba ô lọc trên chạy kiểu nào: "filter" = cổng AND (mặc định, hành vi cũ),
  // "fuse" = mỗi ô thành một kênh retrieval riêng rồi cộng điểm với visual.
  // Giữ qua F5 vì đây là thói quen thao tác, không phải tham số của một lượt.
  const [textMode, setTextMode] = usePersistedState("aic.textmode", "filter");
  const [rerank, setRerank] = usePersistedState("aic.rerank", true);
  const [expand, setExpand] = usePersistedState("aic.expand", true);
  const [selectedVideo, setSelectedVideo] = useState(null);
  // Mục trong giỏ mà trình phát đang chốt frame HỘ ({ id, qid, rank }); null =
  // mở video để xem lại như bình thường, không mọc nút "Chốt frame".
  const [framePick, setFramePick] = useState(null);
  const [frameSequence, setFrameSequence] = useState(null);
  // Cụm frame trùng đang mở (chính object kết quả có .duplicates).
  const [dupeGroup, setDupeGroup] = useState(null);
  // Danh sách model do backend công bố (model nào có index trên đĩa của NÓ).
  const { singles: visualModels, envMembers, defaultModel } = useVisualModels();
  // Giá trị lưu là chuỗi: "siglip" = search đơn, "siglip512+metaclip" = ensemble
  // của đúng hai model đó. localStorage có thể còn model của backend cũ / máy
  // khác - normalizeModel lọc bỏ thứ không còn index, nếu không lần search sau
  // đâm thẳng vào 503.
  const [storedModel, setSelectedModel] = usePersistedState("aic.model", DEFAULT_VISUAL_MODEL);
  const modelValues = useMemo(() => visualModels.map((m) => m.value), [visualModels]);
  // Model GỐC: luôn bật, luôn đứng đầu tổ hợp. Đầu tổ hợp là không gian vector
  // mà temporal và relevance feedback bám vào, nên cho nó trôi theo cú bấm thì
  // tắt nhầm một chip là đổi luôn không gian của hai tính năng kia. Ưu tiên
  // siglip; backend không có index siglip thì lấy model đầu của mặc định.
  const baseModel = useMemo(() => {
    if (modelValues.includes(DEFAULT_VISUAL_MODEL)) return DEFAULT_VISUAL_MODEL;
    const first = String(defaultModel || "").split("+")[0];
    return modelValues.includes(first) ? first : modelValues[0];
  }, [modelValues, defaultModel]);
  // [gốc, ...model trộn thêm theo thứ tự backend] -> chuỗi gửi đi.
  const composeModel = useCallback(
    (list) => [baseModel, ...modelValues.filter((m) => m !== baseModel && list.includes(m))].join("+"),
    [baseModel, modelValues],
  );
  const selectedModel = useMemo(
    () => composeModel(normalizeModel(storedModel, modelValues, envMembers, defaultModel).split("+")),
    [composeModel, storedModel, modelValues, envMembers, defaultModel],
  );
  const activeModels = useMemo(() => selectedModel.split("+"), [selectedModel]);
  // Chỉ bật/tắt được model trộn thêm; model gốc không nhận cú bấm.
  const toggleModel = (name) => {
    if (name === baseModel) return;
    const next = activeModels.includes(name)
      ? activeModels.filter((m) => m !== name)
      : [...activeModels, name];
    setSelectedModel(composeModel(next));
  };

  // --- Phòng nhóm / giỏ / đã xem / lịch sử ---
  // Phòng phải khai báo TRƯỚC giỏ: giỏ nhận `room` để đồng bộ với cả nhóm.
  const room = useRoom();
  // Lấy riêng hai callback ổn định: `room` là object mới mỗi lần render, đưa
  // thẳng vào deps sẽ dựng lại handleSearch/hotkey ở MỌI render.
  const { pushGroupHistory, reportCurrent } = room;
  const basket = useAnswerBasket(room.basketRoom);
  const { markSeen, isSeen, seenCount } = useSeenFrames();
  // Lịch sử cá nhân vẫn giữ (chạy được cả khi tắt phòng); lịch sử nhóm nằm ở
  // room.history và hiển thị ở tab riêng.
  const { history, push: pushHistory, clear: clearHistory } = useQueryHistory();
  const [historyTab, setHistoryTab] = usePersistedState("aic.historytab", "me");

  // Cấu hình nộp bài (taskType/queryId/maxRows) nay thuộc TỪNG CÂU trong `basket`.

  // --- Duyệt kết quả ---
  const [cols, setCols] = usePersistedState("aic.cols", 6);
  const [sortBy, setSortBy] = usePersistedState("aic.sort", "default");
  const [hideSeen, setHideSeen] = usePersistedState("aic.hideseen", false);
  // Backend gộp frame trùng thị giác và trả bản trùng KÈM đại diện
  // (SearchResult.duplicates), nên bung ra chỉ là việc của lưới — không search lại.
  const [showDupes, setShowDupes] = usePersistedState("aic.showdupes", false);
  // Ngưỡng gộp thì NGƯỢC LẠI: nó quyết định cụm được chia thế nào ở backend nên
  // đổi xong phải tìm lại. Hộp thoại Cài đặt có sẵn nút cho việc đó.
  const [dedup, setDedup] = usePersistedState("aic.dedup", true);
  const [dedupThreshold, setDedupThreshold] = usePersistedState("aic.dedupthreshold", 0.975);
  const [videoFilter, setVideoFilter] = useState("");

  // --- Panel/overlay ---
  const [isSubmitOpen, setIsSubmitOpen] = useState(false);
  // Khay nộp bài nằm TRONG khay đáp án, nhưng state để ở đây vì Esc phải đóng
  // nó trước rồi mới đến khay đáp án - thứ tự đó do closeTopOverlay quyết.
  const [isSheetOpen, setIsSheetOpen] = useState(false);
  // Xem trước CSV mở đè lên khay nộp bài - cùng lý do trên, Esc phải đóng nó
  // trước khay.
  const [isCsvPreviewOpen, setIsCsvPreviewOpen] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isHelpOpen, setIsHelpOpen] = useState(false);
  const [isQuestionOpen, setIsQuestionOpen] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  // Bề rộng cửa sổ -> giới hạn số cột lưới trên màn hình nhỏ.
  const [vw, setVw] = useState(typeof window !== "undefined" ? window.innerWidth : 1280);
  useEffect(() => {
    const onResize = () => setVw(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  const effectiveCols = useMemo(() => {
    if (vw < 640) return Math.min(cols, 2);
    if (vw < 1024) return Math.min(cols, 4);
    return cols;
  }, [vw, cols]);

  const [temporalData, setTemporalData] = useState({
    events: [emptyEvent()],
    model: DEFAULT_VISUAL_MODEL,
    topk_per_event: 200,
  });

  // --- Gallery (dùng chung cho mọi loại truy vấn) ---
  const [openLightbox, setOpenLightbox] = useState(false);
  const [currentImageIndex, setCurrentImageIndex] = useState(0);

  // --- Điều hướng lưới ---
  const [focusedIndex, setFocusedIndex] = useState(0);
  const focusedRef = useRef(null);
  const queryRef = useRef(null);
  const chatInputRef = useRef(null);

  // --- Ngữ cảnh cho relevance feedback / hỏi đáp agent ---
  // Chính là các frame trong giỏ của CÂU ĐANG TRẢ LỜI (không còn "vùng nháp" riêng).
  const [feedbackLoading, setFeedbackLoading] = useState(false);
  const selectedIds = useMemo(() => basket.items.map((it) => it.id), [basket.items]);

  // MỘT danh sách phẳng cho MỌI chế độ (grid/grouped/temporal) - nguồn chung
  // của lưới, bộ lọc, gallery và phím tắt. Nhóm ASR/Temporal vẫn tự trình bày
  // bố cục riêng nhưng lấy đúng các object trong danh sách này.
  const groupedResults = useMemo(() => flattenResults(results, resultType), [results, resultType]);

  // Số frame đang bị gộp — hiện lên toolbar, nếu không thì việc lưới ngắn đi là
  // một hộp đen (dễ tưởng truy vấn ra ít kết quả).
  const dupeCount = useMemo(
    () => groupedResults.reduce((n, r) => n + (r.duplicate_count || 0), 0),
    [groupedResults]
  );

  // Bung bản trùng ngay sau đại diện của nó, giữ nguyên thứ tự điểm trong cụm.
  const flatResults = useMemo(
    () =>
      showDupes
        ? groupedResults.flatMap((r) => [r, ...(r.duplicates || [])])
        : groupedResults,
    [groupedResults, showDupes]
  );

  const gridResults = useMemo(() => {
    let list = flatResults.filter((r) => r.frame_url);
    if (videoFilter) list = list.filter((r) => r.video_name === videoFilter);
    if (hideSeen) list = list.filter((r) => !isSeen(r.id));
    if (sortBy === "score") list = [...list].sort((a, b) => (b.score || 0) - (a.score || 0));
    else if (sortBy === "video")
      list = [...list].sort((a, b) => String(a.video_name).localeCompare(String(b.video_name)) || (b.score || 0) - (a.score || 0));
    return list;
  }, [flatResults, videoFilter, hideSeen, sortBy, isSeen]);

  // id -> vị trí trong gridResults. Nhóm ASR/Temporal dựng lại object mỗi lần
  // render nên KHÔNG thể so sánh bằng tham chiếu; tra theo id vừa đúng vừa O(1).
  const indexById = useMemo(
    () => new Map(gridResults.map((r, i) => [r.id, i])),
    [gridResults]
  );

  // Nhóm dùng để lấy đúng object đang nằm trong lưới (null nếu đã bị lọc bỏ).
  const resolveResult = useCallback(
    (id) => {
      const idx = indexById.get(id);
      return idx == null ? null : gridResults[idx];
    },
    [indexById, gridResults]
  );

  const videoList = useMemo(() => {
    const s = new Set(flatResults.filter((r) => r.frame_url).map((r) => r.video_name));
    return Array.from(s).sort();
  }, [flatResults]);

  // Ô đang được chọn (đồng bộ với gallery) - nhóm ASR/Temporal so khớp theo id vì
  // chúng không render theo chỉ số của gridResults.
  const focusedResult = gridResults[focusedIndex] || null;

  useEffect(() => {
    setFocusedIndex(0);
    setVideoFilter("");
  }, [results]);

  useEffect(() => {
    // inline: dải sự kiện temporal cuộn NGANG nên cần cả trục này.
    focusedRef.current?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [focusedIndex, gridResults.length]);

  // Tham chiếu ổn định cho các callback truyền xuống lưới - nhờ vậy
  // React.memo(ResultItem) không bị vô hiệu mỗi khi gridResults đổi.
  const gridResultsRef = useRef(gridResults);
  gridResultsRef.current = gridResults;
  const indexByIdRef = useRef(indexById);
  indexByIdRef.current = indexById;

  // Đóng băng danh sách slide trong lúc gallery đang mở. Nếu không, việc đánh
  // dấu "đã xem" khi lướt sẽ làm gridResults co lại ngay dưới chân (khi bật
  // "Ẩn đã xem") và mọi chỉ số slide lệch đi.
  const galleryResultsRef = useRef(gridResults);
  if (!openLightbox) galleryResultsRef.current = gridResults;
  const galleryResults = galleryResultsRef.current;

  const openImageViewer = useCallback((index) => {
    setCurrentImageIndex(index);
    setOpenLightbox(true);
    const r = gridResultsRef.current[index];
    if (r) markSeen(r.id);
  }, [markSeen]);

  // Giữ hợp đồng onImageClick(result) cho cả lưới lẫn AsrResultGroup/
  // TemporalResultGroup: tra index theo id (không so sánh tham chiếu).
  const openImageForResult = useCallback((result) => {
    const idx = indexByIdRef.current.get(result?.id);
    if (idx != null) openImageViewer(idx);
  }, [openImageViewer]);

  const openVideo = useCallback((r) => {
    if (r) markSeen(r.id);
    // Hạ mục đang chốt: mở video từ lưới kết quả mà còn sót framePick của lần
    // trước thì nút "Chốt frame" hiện lên trỏ vào một dòng chẳng liên quan.
    setFramePick(null);
    setSelectedVideo(r);
  }, [markSeen]);

  // Bóc ra hai thứ DUY NHẤT mà hai hook dưới đây cần từ giỏ. Phụ thuộc cả
  // `basket` thì hỏng: object đó dựng mới mỗi render, nên hai hàm này sẽ đổi
  // tham chiếu theo từng ký tự gõ vào ô đáp án và kéo memo(AnswerRow) mất tác
  // dụng ở mọi dòng trong giỏ. `basketCurrent` là số, `basketItemsOf` đã được
  // useCallback sẵn - cả hai đều là dependency đúng nghĩa.
  const basketCurrent = basket.current;
  const basketItemsOf = basket.itemsOf;

  // Mở video ở CHẾ ĐỘ CHỐT FRAME cho một dòng trong giỏ đáp án.
  const openVideoForPick = useCallback((item, rank) => {
    if (!item) return;
    markSeen(item.id);
    setFramePick({ id: item.id, qid: basketCurrent, rank });
    setSelectedVideo(item);
  }, [markSeen, basketCurrent]);

  const closeVideo = useCallback(() => {
    setSelectedVideo(null);
    setFramePick(null);
  }, []);

  // Frame ĐANG LƯU của mục được chốt, đọc từ giỏ chứ không chụp lại lúc mở: chốt
  // xong không đóng modal, nên số này phải cập nhật ngay để dòng "Δ" nói thật.
  const pickState = useMemo(() => {
    if (!framePick) return null;
    const it = basketItemsOf(framePick.qid).find((x) => x.id === framePick.id);
    // Mục bị xoá (đồng đội xoá trong lúc mình đang chốt) -> thôi chốt.
    if (!it) return null;
    return { ...framePick, frame_idx: it.frame_idx ?? null };
  }, [framePick, basketItemsOf]);

  const openFrames = useCallback((r) => {
    if (r) markSeen(r.id);
    setFrameSequence(r);
  }, [markSeen]);

  const handleFeedbackSearch = async () => {
    if (!selectedIds.length || feedbackLoading) return;
    setFeedbackLoading(true);
    try {
      const list = await searchFeedback(selectedIds, textQuery, k, selectedModel);
      injectResults(list, 'grid');
    } catch (err) {
      console.error("Feedback search error:", err);
    } finally {
      setFeedbackLoading(false);
    }
  };

  const handleModeChange = (newMode) => {
    setMode(newMode);
    setTextQuery("");
    setOcrQuery("");
    setAsrQuery("");
    setImageFile(null);
    setOcrFilter("");
    setAsrFilter("");
    setTemporalData({
      events: [emptyEvent()],
      model: 'siglip',
      topk_per_event: 200,
    });
    clearSearchState();
  };

  const handleSearch = useCallback(() => {
    let query = "";
    if (mode === 'text') query = textQuery;
    else if (mode === 'ocr') query = ocrQuery;
    else if (mode === 'asr') query = asrQuery;

    if (query && query.trim()) {
      pushHistory(mode, query);
      // Đẩy lên phòng để cả nhóm thấy hướng đã dò, khỏi tìm trùng đường.
      pushGroupHistory(mode, query);
    }

    setIsSidebarOpen(false); // thu gọn drawer trên mobile để thấy kết quả
    executeSearch({
      mode, query, imageFile, k, model: selectedModel,
      ocrFilter, asrFilter, captionFilter, textMode, rerank, expand, temporalData,
      dedup, dedupThreshold,
    });
  }, [mode, textQuery, ocrQuery, asrQuery, imageFile, k, selectedModel, ocrFilter, asrFilter, captionFilter, textMode, rerank, expand, temporalData, dedup, dedupThreshold, executeSearch, pushHistory, pushGroupHistory]);

  // Cho cả nhóm biết mình đang ở câu nào (hiện trên avatar ở MemberBar).
  const currentQuestion = basket.current;
  useEffect(() => {
    reportCurrent(currentQuestion);
  }, [currentQuestion, reportCurrent]);

  const runHistory = (item) => {
    setMode(item.mode);
    if (item.mode === 'text') setTextQuery(item.query);
    else if (item.mode === 'ocr') setOcrQuery(item.query);
    else if (item.mode === 'asr') setAsrQuery(item.query);
    executeSearch({
      mode: item.mode, query: item.query, imageFile: null, k, model: selectedModel,
      ocrFilter, asrFilter, captionFilter, textMode, rerank, expand, temporalData,
    });
  };

  // --- Phím tắt ---
  const closeTopOverlay = useCallback(() => {
    // Gallery nằm trên cùng: không chặn ở đây thì ESC vừa đóng gallery (lightbox
    // tự xử lý) vừa đóng luôn khay nộp / modal ở phía dưới.
    if (openLightbox) return setOpenLightbox(false);
    if (isHelpOpen) return setIsHelpOpen(false);
    if (isSettingsOpen) return setIsSettingsOpen(false);
    if (frameSequence) return setFrameSequence(null);
    if (dupeGroup) return setDupeGroup(null);
    if (selectedVideo) return closeVideo();
    if (isQuestionOpen) return setIsQuestionOpen(false);
    // Xem trước CSV mở ĐÈ lên khay nộp bài -> phải đóng trước khay.
    if (isCsvPreviewOpen) return setIsCsvPreviewOpen(false);
    if (isSheetOpen) return setIsSheetOpen(false);
    if (isSubmitOpen) return setIsSubmitOpen(false);
  }, [openLightbox, isHelpOpen, isSettingsOpen, frameSequence, dupeGroup, selectedVideo, closeVideo, isQuestionOpen, isCsvPreviewOpen, isSheetOpen, isSubmitOpen]);

  // Chỉ còn ba phím tắt: 1, 2 (đổi tab panel) và s (mở/đóng giỏ đáp án).
  // Esc giữ lại vì đó là cách đóng modal chuẩn, không phải phím tắt thao tác.
  const onHotkey = useCallback((e) => {
    if (e.key === "Escape") { closeTopOverlay(); return; }
    if (isEditableTarget(e)) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;

    // Gallery mở thì ba phím này chỉ đổi/mở panel nằm phía SAU lightbox - bấm
    // trúng lúc đang soi ảnh chỉ gây rối, nên bỏ qua hết.
    if (openLightbox) return;

    if (e.key === "1") { e.preventDefault(); setPanelTab("manual"); return; }
    if (e.key === "2") { e.preventDefault(); setPanelTab("agent"); return; }
    if (e.key === "s") { e.preventDefault(); setIsSubmitOpen((v) => !v); }
  }, [closeTopOverlay, setPanelTab, openLightbox]);

  useHotkeys(onHotkey, true);

  const seg = (active) =>
    `flex flex-col items-center justify-center gap-1 py-2 rounded-md text-[11px] font-semibold transition-colors ${
      active ? "bg-white shadow-sm text-blue-600" : "text-slate-500 hover:text-slate-800 hover:bg-white/50"
    }`;

  // Tab cấp cao Thủ công / Agent: kiểu underline - khác hẳn khay pill của seg()
  // để phân biệt rõ cấp điều hướng 1 với các segmented control bên trong panel.
  const tab = (active) =>
    `relative -mb-px inline-flex items-center justify-center gap-2 flex-1 py-3 border-b-2 text-sm font-semibold transition-colors ${
      active
        ? "border-blue-600 text-blue-600"
        : "border-transparent text-slate-500 hover:text-slate-800 hover:border-slate-300"
    }`;

  return (
    <div className="flex flex-col h-screen bg-slate-50 text-slate-900">
      {/* ===== TOP BAR ===== */}
      <header className="flex items-center gap-2 sm:gap-4 px-3 sm:px-4 h-14 bg-white border-b border-slate-200 shrink-0">
        {/* Toggle sidebar (mobile) */}
        <button onClick={() => setIsSidebarOpen((v) => !v)} className={`${iconBtn} lg:hidden shrink-0`} title="Bảng điều khiển tìm kiếm">
          <MenuIcon />
        </button>

        {/* Brand - mark trùng favicon; wordmark canh baseline bằng leading-none
            + margin thay vì leading-tight để hai dòng không bị "trôi" so với ô
            logo. Chữ "2026" tô xanh làm điểm nhấn duy nhất, ăn với accent chung. */}
        <div className="flex items-center gap-2.5 shrink-0">
          <AicMark className="w-8 h-8 shrink-0 rounded-lg shadow-sm ring-1 ring-slate-900/10" />
          <div className="hidden sm:block">
            <div className="text-[15px] font-bold leading-none tracking-tight text-slate-900 whitespace-nowrap">
              AIC <span className="text-blue-600">2026</span>
            </div>
            <div className="mt-1 text-[9.5px] font-semibold uppercase leading-none tracking-[0.16em] text-slate-400 whitespace-nowrap">
              Video Retrieval
            </div>
          </div>
        </div>

        <div className="flex-1" />

        {/* Cụm phải: trạng thái phòng | công cụ | hành động chính. Ba nhóm cách
            nhau bằng khoảng trắng chứ không phải bằng vạch kẻ khắp nơi - chỉ
            còn ĐÚNG MỘT vạch, ngăn "thông tin" với "nút bấm". Hai nút icon dính
            sát nhau (gap nhỏ hơn gap của header) để đọc ra là một cặp. */}
        <div className="flex items-center gap-2 shrink-0">
          <MemberBar room={room} />

          <span aria-hidden className="mx-0.5 h-5 w-px bg-slate-200" />

          <div className="flex items-center gap-0.5">
            <button onClick={() => setIsHelpOpen(true)} className={iconBtn} title="Phím tắt"><KeyboardIcon /></button>
            <button onClick={() => setIsSettingsOpen(true)} className={iconBtn} title="Cài đặt"><SettingsIcon /></button>
          </div>
        </div>

        {/* Giỏ đáp án là nút bấm nhiều nhất lúc thi nên đặt CUỐI cùng, sát mép
            phải: góc màn hình là đích "vô hạn bề rộng" (Fitts) - quăng chuột hết
            cỡ sang phải là trúng, không cần ngắm. Vì vậy nó nuốt luôn padding
            phải của header (-mr-3/-mr-4 bù lại px-3/sm:px-4) và cao hết thanh.
            KHÔNG bo góc: bo cạnh trái làm mảng xanh trông như cái tab bị lệch,
            trong khi cạnh phải vẫn vuông theo mép màn hình - hai bên không ăn
            nhập. Vuông hết thì nó đọc ra là một cột liền của header. */}
        <button
          onClick={() => setIsSubmitOpen(true)}
          className="group relative ml-1 -mr-3 sm:-mr-4 self-stretch inline-flex items-center gap-2 bg-blue-600 pl-4 pr-3 sm:pr-5 text-sm font-semibold text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.18)] transition-colors hover:bg-blue-700 active:bg-blue-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-white/70 shrink-0"
          title={`Giỏ đáp án: các frame sẽ export/nộp để chấm điểm (phím s). Toàn đề ${basket.totalCount} đáp án, câu ${basket.current} đang có ${basket.count}.`}
        >
          <InboxIcon className="w-4 h-4 shrink-0" />
          <span className="hidden sm:inline">Giỏ đáp án</span>
          {/* Badge đếm CẢ ĐỀ: câu đang làm và số đáp án của riêng nó đã có pill
              QuestionSwitcher ở góc dưới-phải lo, không lặp lại ở đây. Đặt NẰM
              TRONG hàng chữ thay vì nhô ra góc - nút đã sát mép màn hình, badge
              nổi ở góc sẽ bị mép cắt. */}
          {basket.totalCount > 0 && (
            <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-amber-300 px-1.5 text-[11px] font-bold text-slate-900 tabular-nums">
              {basket.totalCount}
            </span>
          )}
          <kbd className="hidden lg:inline rounded border border-white/30 bg-white/10 px-1 text-[10px] font-mono font-normal leading-[1.4] text-white/80 transition-colors group-hover:border-white/50">
            s
          </kbd>
        </button>
      </header>

      {/* Key LLM hết lượt -> cả hệ degrade ÂM THẦM (xem LlmQuotaBanner). Đặt
          ngay dưới header, chiếm hết bề ngang: cảnh báo mức toàn hệ, không
          thuộc riêng panel tìm kiếm hay panel agent. */}
      <LlmQuotaBanner onOpenSettings={() => setIsSettingsOpen(true)} />

      <div className="flex flex-1 min-h-0">
        {/* Nền mờ cho drawer (mobile) */}
        {isSidebarOpen && (
          <div className="fixed inset-0 top-14 z-30 bg-black/30 lg:hidden" onClick={() => setIsSidebarOpen(false)} />
        )}

        {/* ===== SIDEBAR ===== */}
        <aside className={`fixed lg:static top-14 lg:top-0 bottom-0 left-0 z-40 w-[85%] max-w-[340px] lg:w-[440px] lg:max-w-none lg:h-full flex flex-col bg-white border-r border-slate-200 overflow-hidden shadow-xl lg:shadow-none transform transition-transform duration-200 ${isSidebarOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"}`}>
          {/* Tab cấp cao: Thủ công / Agent */}
          <div className="flex items-stretch px-4 border-b border-slate-200 shrink-0" role="tablist">
            <button role="tab" aria-selected={panelTab === "manual"} className={tab(panelTab === "manual")} onClick={() => setPanelTab("manual")} title="Form tìm kiếm thủ công (phím 1)">
              <SearchIcon className="w-4 h-4" /> Thủ công
              <kbd className="hidden sm:inline text-[10px] font-mono font-normal text-slate-400 border border-slate-200 rounded px-1">1</kbd>
            </button>
            <button role="tab" aria-selected={panelTab === "agent"} className={tab(panelTab === "agent")} onClick={() => setPanelTab("agent")} title="Trợ lý: tìm kiếm hội thoại & hỏi đáp (phím 2)">
              <ChatIcon className="w-4 h-4" /> Agent
              <kbd className="hidden sm:inline text-[10px] font-mono font-normal text-slate-400 border border-slate-200 rounded px-1">2</kbd>
            </button>
          </div>

          {/* ===== TAB THỦ CÔNG ===== */}
          <div className={`${panelTab === "manual" ? "flex" : "hidden"} flex-col flex-1 min-h-0 p-4 space-y-4 overflow-y-auto`}>
            {/* Mode */}
            <div className="grid grid-cols-5 gap-1 bg-slate-100 p-1 rounded-xl">
              {MODES.map((m) => (
                <button key={m.id} className={seg(mode === m.id)} onClick={() => handleModeChange(m.id)} title={m.label}>
                  <m.Icon className="w-4 h-4" />
                  {m.label}
                </button>
              ))}
            </div>

            {/* Input */}
            <div>
              {mode === 'text' && <textarea ref={queryRef} className={`${field} h-28`} value={textQuery} onChange={(e) => setTextQuery(e.target.value)} placeholder="Nhập mô tả cảnh cần tìm…" />}
              {mode === 'ocr' && <textarea ref={queryRef} className={`${field} h-28`} value={ocrQuery} onChange={(e) => setOcrQuery(e.target.value)} placeholder="Nhập chữ xuất hiện trên màn hình…" />}
              {mode === 'asr' && <textarea ref={queryRef} className={`${field} h-28`} value={asrQuery} onChange={(e) => setAsrQuery(e.target.value)} placeholder="Nhập lời thoại cần tìm…" />}
              {mode === 'image' && (
                <label htmlFor="image-upload" className="flex flex-col items-center justify-center gap-1 border-2 border-dashed border-slate-300 rounded-lg p-6 text-center cursor-pointer hover:border-blue-400 hover:bg-slate-50 transition">
                  <UploadIcon className="w-6 h-6 text-slate-400" />
                  <p className="font-medium text-sm text-blue-600 break-words">{imageFile ? imageFile.name : 'Tải ảnh lên'}</p>
                  <input id="image-upload" type="file" className="hidden" accept="image/*" onChange={(e) => setImageFile(e.target.files[0])} />
                </label>
              )}
              {mode === 'temporal' && <TemporalInput temporalData={temporalData} setTemporalData={setTemporalData} />}
            </div>

            {/* Model — chip nhiều lựa chọn thay cho <select>: bật 1 model =
                search đơn, bật ≥2 = ensemble của đúng những model đó, quyết
                định ngay tại lượt search này. So (siglip+clip) với
                (siglip512+metaclip) trên cùng một truy vấn giờ là hai cú bấm,
                không phải sửa .env rồi chờ backend nạp lại model 10 phút. */}
            {(mode !== 'asr' && mode !== 'ocr') && (
              <div className={card}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-semibold text-slate-700">Model</span>
                  <span className={`rounded-full px-2 py-0.5 text-[10.5px] font-semibold ${
                    activeModels.length > 1
                      ? "bg-blue-100 text-blue-700"
                      : "bg-slate-200/70 text-slate-500"
                  }`}>
                    {activeModels.length > 1 ? `Ensemble · ${activeModels.length}` : "Search đơn"}
                  </span>
                </div>
                {/* Lưới 2 cột: tên model dài ngắn khác nhau nên wrap tự do để lại
                    một chip lẻ ở hàng cuối. Model gốc nằm luôn ô đầu, làm mờ và
                    không bấm được - vẫn ở trong lưới để thấy đủ "đang search trên
                    những gì" chỉ trong một khung. */}
                <div className="grid grid-cols-2 gap-1.5">
                  {visualModels.map((m) => {
                    const isBase = m.value === baseModel;
                    const on = activeModels.includes(m.value);
                    const body = (
                      <>
                        <span className={`grid h-4 w-4 shrink-0 place-items-center rounded border transition-colors ${
                          isBase
                            ? "border-slate-300 bg-slate-300 text-white"
                            : on
                              ? "border-blue-600 bg-blue-600 text-white"
                              : "border-slate-300 bg-white"
                        }`}>
                          {(isBase || on) && <CheckIcon className="h-3 w-3" strokeWidth={3} />}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate font-mono text-[11.5px] font-semibold leading-tight">
                            {m.value}
                          </span>
                          <span className={`block text-[10px] leading-tight tabular-nums ${
                            isBase ? "text-slate-400" : on ? "text-blue-500" : "text-slate-400"
                          }`}>
                            {isBase ? `${m.dim ? `${m.dim} · ` : ""}gốc` : m.dim || " "}
                          </span>
                        </span>
                      </>
                    );
                    // Model gốc: <div> chứ không phải <button disabled> - không có
                    // gì để bấm thì đừng để nó nhận focus Tab hay đổi con trỏ.
                    return isBase ? (
                      <div
                        key={m.value}
                        title="Model gốc, luôn bật: temporal và relevance feedback chạy trên không gian vector này"
                        className="flex items-center gap-2 rounded-lg border border-dashed border-slate-300 bg-slate-100/80 px-2 py-1.5 text-slate-400 select-none"
                      >
                        {body}
                      </div>
                    ) : (
                      <button
                        key={m.value}
                        type="button"
                        onClick={() => toggleModel(m.value)}
                        aria-pressed={on}
                        title={on ? `Bỏ ${m.value} khỏi tổ hợp` : `Trộn thêm ${m.value}`}
                        className={`flex items-center gap-2 rounded-lg border px-2 py-1.5 text-left transition-colors ${
                          on
                            // Nền xanh nhạt + viền xanh thay cho xanh đặc: vẫn
                            // nổi hẳn so với ô tắt, mà không nặng hơn các khối
                            // khác của sidebar (cùng tông với nút Lọc/Trộn điểm).
                            ? "border-blue-400 bg-blue-50 text-blue-800 shadow-sm"
                            : "border-slate-200 bg-white text-slate-600 hover:border-blue-300 hover:bg-blue-50/40"
                        }`}
                      >
                        {body}
                      </button>
                    );
                  })}
                </div>
                <p className="text-[11px] leading-snug text-slate-400 mt-2">
                  {activeModels.length > 1
                    ? <>Trộn điểm (chuẩn hoá theo max) của <b className="font-mono font-semibold text-slate-500">{activeModels.join(" + ")}</b>.</>
                    : <>Tích thêm model để trộn điểm với <b className="font-mono font-semibold text-slate-500">{baseModel}</b>.</>}
                </p>
              </div>
            )}

            {/* Filter */}
            {mode !== 'temporal' && mode !== 'ocr' && mode !== 'asr' && (
              <div className={`${card} space-y-2`}>
                <h2 className="text-sm font-semibold text-slate-700">Bộ lọc</h2>
                {/* Hai cách dùng CÙNG ba ô dưới, khác nhau về bản chất:
                    Lọc  = cổng AND trên pool visual (recall trần = pool đó);
                    Trộn = mỗi ô thành một kênh retrieval riêng, cộng điểm với
                           visual - kéo được frame mà visual trượt hẳn. */}
                {mode === 'text' && (
                  <div className="grid grid-cols-2 gap-1 bg-slate-100 p-1 rounded-lg">
                    {[["filter", "Lọc", "Chỉ giữ frame có đủ chữ - nhanh, chặt, nhưng không tìm thêm frame mới"],
                      ["fuse", "Trộn điểm", "Mỗi ô là một kênh tìm riêng (OCR/ASR/caption), điểm cộng với visual"]].map(([value, label, hint]) => (
                      <button
                        key={value}
                        type="button"
                        onClick={() => setTextMode(value)}
                        aria-pressed={textMode === value}
                        title={hint}
                        className={`py-1 rounded-md text-xs font-semibold transition-colors ${
                          textMode === value ? "bg-white shadow-sm text-blue-600" : "text-slate-500 hover:text-slate-800"
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                )}
                <input type="text" className={field} placeholder="Lọc theo OCR…" value={ocrFilter} onChange={(e) => setOcrFilter(e.target.value)} />
                <input type="text" className={field} placeholder="Lọc theo ASR…" value={asrFilter} onChange={(e) => setAsrFilter(e.target.value)} />
                {/* Chỉ /search_text đọc bộ lọc caption. Caption do Qwen2.5-VL
                    sinh bằng TIẾNG ANH và là văn xuôi, nên lọc theo TỪ (mọi từ
                    phải có mặt, thứ tự tuỳ ý) chứ không so cả cụm như OCR. */}
                {mode === 'text' && (
                  <>
                    <input
                      type="text"
                      className={field}
                      placeholder="Lọc theo caption… (tiếng Anh)"
                      value={captionFilter}
                      onChange={(e) => setCaptionFilter(e.target.value)}
                    />
                    {captionTranslation ? (
                      <p className="text-[11px] text-blue-600">
                        Đã dịch sang <b className="font-mono">{captionTranslation}</b> — lọc theo cả
                        bản dịch lẫn chữ bạn gõ.
                      </p>
                    ) : (
                      <p className="text-[11px] text-slate-400">
                        Caption sinh bằng tiếng Anh; gõ tiếng Việt CÓ DẤU thì tự dịch. Nhiều từ =
                        phải có ĐỦ, thứ tự tuỳ ý (vd <span className="font-mono">man motorbike</span>).
                        Frame chưa có caption bị loại.
                      </p>
                    )}
                  </>
                )}
              </div>
            )}

            {/* Rerank / expand */}
            {(mode === 'text' || mode === 'ocr' || mode === 'asr') && (
              <div className={`${card} space-y-3`}>
                <label className="flex items-center justify-between cursor-pointer">
                  <span className="text-sm font-semibold text-slate-700">Rerank <span className="text-xs text-slate-400 font-normal">(chính xác hơn, chậm hơn)</span></span>
                  <input type="checkbox" className="w-4 h-4 accent-blue-600" checked={rerank} onChange={(e) => setRerank(e.target.checked)} />
                </label>
                {mode === 'text' && (
                  <label className="flex items-center justify-between cursor-pointer">
                    <span className="text-sm font-semibold text-slate-700">Dịch &amp; mở rộng <span className="text-xs text-slate-400 font-normal">(AI)</span></span>
                    <input type="checkbox" className="w-4 h-4 accent-blue-600" checked={expand} onChange={(e) => setExpand(e.target.checked)} />
                  </label>
                )}
              </div>
            )}

            {/* Top K */}
            {mode !== 'temporal' && (
              <div className={card}>
                <label htmlFor="kInput" className="block text-sm font-semibold text-slate-700">Top K: <span className="text-blue-600 tabular-nums">{k}</span></label>
                <input type="number" id="kInput" min="1" value={k} onChange={(e) => setK(Math.max(1, Number(e.target.value) || 1))} className={`${field} mt-2`} />
                <input type="range" id="kRange" min="25" max="1000" step="25" value={Math.min(k, 1000)} onChange={(e) => setK(Number(e.target.value))} className="w-full mt-2 accent-blue-600" />
                <p className="text-xs text-slate-400 mt-1">Nhập số bất kỳ. Thanh trượt tới 1000 cho tiện.</p>
              </div>
            )}

            {/* Lịch sử - của mình và của cả nhóm. Lịch sử nhóm để không ai dò
                lại đúng hướng đồng đội vừa dò xong. */}
            {(history.length > 0 || (room.active && room.history.length > 0)) && (
              <div className={card}>
                <div className="flex justify-between items-center mb-2">
                  <div className="inline-flex items-center gap-1 text-sm font-semibold text-slate-700">
                    <ClockIcon className="w-4 h-4" />
                    <button
                      onClick={() => setHistoryTab("me")}
                      className={historyTab === "me" ? "text-slate-800 underline underline-offset-4" : "text-slate-400 hover:text-slate-600"}
                    >
                      Của tôi
                    </button>
                    {room.active && (
                      <>
                        <span className="text-slate-300">/</span>
                        <button
                          onClick={() => setHistoryTab("group")}
                          className={historyTab === "group" ? "text-slate-800 underline underline-offset-4" : "text-slate-400 hover:text-slate-600"}
                        >
                          Nhóm {room.history.length > 0 && <span className="tabular-nums">({room.history.length})</span>}
                        </button>
                      </>
                    )}
                  </div>
                  {historyTab === "me" && (
                    <button onClick={clearHistory} className="text-xs text-slate-400 hover:text-slate-700">Xoá</button>
                  )}
                </div>
                <ul className="space-y-1 max-h-40 overflow-y-auto">
                  {historyTab === "me"
                    ? history.slice(0, 12).map((h) => (
                        <li key={h.id}>
                          <button onClick={() => runHistory(h)} className="w-full text-left text-xs bg-white border border-slate-200 hover:border-blue-300 hover:bg-blue-50 rounded px-2 py-1 truncate transition" title={h.query}>
                            <span className="text-blue-600 font-semibold uppercase">{h.mode}</span> · {h.query}
                          </button>
                        </li>
                      ))
                    : room.history.slice(0, 20).map((h) => (
                        <li key={h.id}>
                          <button
                            onClick={() => runHistory(h)}
                            className="w-full flex items-center gap-1.5 text-left text-xs bg-white border border-slate-200 hover:border-blue-300 hover:bg-blue-50 rounded px-2 py-1 transition"
                            title={`${h.member_name}: ${h.query}`}
                          >
                            <span className={`shrink-0 w-4 h-4 rounded-full ${memberColor(h.member_name)} text-white text-[8px] font-bold flex items-center justify-center`}>
                              {initials(h.member_name)}
                            </span>
                            <span className="text-blue-600 font-semibold uppercase shrink-0">{h.mode}</span>
                            <span className="truncate">{h.query}</span>
                          </button>
                        </li>
                      ))}
                </ul>
              </div>
            )}

            {/* Search */}
            <div className="flex-grow" />
            <button onClick={handleSearch} className="w-full inline-flex items-center justify-center gap-2 bg-blue-600 text-white py-3 rounded-lg hover:bg-blue-700 font-semibold disabled:bg-slate-300 transition-colors" disabled={isLoading}>
              <SearchIcon className="w-5 h-5" /> {isLoading ? 'Đang tìm…' : 'Tìm kiếm'}
            </button>
          </div>

          {/* ===== TAB AGENT ===== */}
          {/* Luôn mounted (chỉ ẩn bằng CSS) để giữ lịch sử chat khi đổi tab. */}
          <AgentChatPanel
            isOpen={panelTab === "agent"}
            model={selectedModel}
            topK={k}
            selectedIds={selectedIds}
            currentQuestion={basket.current}
            /* Dạng đề CHỈ tin khi đã nạp gói truy vấn của BTC (queryText có nội
               dung). Câu chưa nạp đề mặc định taskType="kis" - gửi nó lên sẽ ép
               nhầm mọi câu hỏi gõ tay thành tìm kiếm; để rỗng cho backend tự
               nhận dạng. */
            taskType={basket.queryText ? basket.taskType : ""}
            onResults={injectResults}
            inputRef={chatInputRef}
            /* Lịch sử tra cứu Agent lưu ở server theo member_id -> cần biết
               phòng có đang bật không. Tắt phòng thì panel chỉ giữ bản nháp
               trên máy này và nói rõ điều đó. */
            roomActive={room.active}
          />
        </aside>

        {/* ===== MAIN ===== */}
        <main className="flex-1 h-full flex flex-col overflow-hidden">
          {/* Toolbar duyệt */}
          {!isLoading && !error && resultType === 'grid' && results.length > 0 && (
            <div className="flex flex-wrap items-center gap-4 px-4 py-2.5 bg-white border-b border-slate-200 text-sm shrink-0">
              <span className="text-slate-600 font-semibold tabular-nums">{gridResults.length} / {results.length} kết quả</span>
              <div className="flex items-center gap-1">
                <span className="text-slate-400">Cột</span>
                {[4, 6, 8, 10].map((c) => (
                  <button key={c} onClick={() => setCols(c)} className={`w-7 h-7 rounded text-xs font-semibold transition-colors ${cols === c ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}>{c}</button>
                ))}
              </div>
              <label className="flex items-center gap-1.5">
                <span className="text-slate-400">Sắp xếp</span>
                <select value={sortBy} onChange={(e) => setSortBy(e.target.value)} className="bg-white border border-slate-300 rounded px-2 py-1 text-xs">
                  <option value="default">Mặc định</option>
                  <option value="score">Điểm cao → thấp</option>
                  <option value="video">Theo video</option>
                </select>
              </label>
              <label className="flex items-center gap-1.5">
                <span className="text-slate-400">Video</span>
                <select value={videoFilter} onChange={(e) => setVideoFilter(e.target.value)} className="bg-white border border-slate-300 rounded px-2 py-1 text-xs max-w-[10rem]">
                  <option value="">Tất cả ({videoList.length})</option>
                  {videoList.map((v) => <option key={v} value={v}>{v}</option>)}
                </select>
              </label>
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input type="checkbox" className="accent-blue-600" checked={hideSeen} onChange={(e) => setHideSeen(e.target.checked)} />
                <span className="text-slate-500">Ẩn đã xem ({seenCount})</span>
              </label>
              {dupeCount > 0 && (
                <label className="flex items-center gap-1.5 cursor-pointer" title="Frame trùng thị giác đã được gộp vào ô đại diện (kể cả khi ở video khác)">
                  <input type="checkbox" className="accent-blue-600" checked={showDupes} onChange={(e) => setShowDupes(e.target.checked)} />
                  <span className="text-slate-500">Hiện bản trùng ({dupeCount})</span>
                </label>
              )}
            </div>
          )}

          <div className="flex-1 overflow-y-auto p-4">
            {isLoading && <p className="text-center text-slate-400 mt-8">Đang tìm kiếm…</p>}
            {!isLoading && error && <p className="text-center text-red-500 mt-8">{error}</p>}
            {!isLoading && !error && results.length === 0 && (
              <div className="flex flex-col items-center justify-center h-full text-slate-300">
                <SearchIcon className="w-12 h-12" />
                <p className="mt-3 text-slate-400 text-sm">
                  {hasSearched
                    ? "Truy vấn này không ra kết quả nào - thử đổi từ khoá hoặc chế độ."
                    : "Nhập truy vấn để bắt đầu tìm kiếm."}
                </p>
              </div>
            )}

            {!isLoading && !error && results.length > 0 && (
              resultType === 'grouped' ? <div>{results.map((group) => <AsrResultGroup key={group.video_name} videoGroup={group} resolve={resolveResult} onVideoClick={openVideo} onImageClick={openImageForResult} onFramesClick={openFrames} basketRankOf={basket.rankOf} basketQuestionOf={basket.questionOf} currentQuestion={basket.current} onToggleBasket={basket.toggle} focusedId={focusedResult?.id} focusedRef={focusedRef} isSeen={isSeen} />)}</div> :
              resultType === 'temporal' ? <div>{results.map((group) => <TemporalResultGroup key={group.video_name} videoGroup={group} resolve={resolveResult} onVideoClick={openVideo} onImageClick={openImageForResult} onFramesClick={openFrames} basketRankOf={basket.rankOf} basketQuestionOf={basket.questionOf} currentQuestion={basket.current} onToggleBasket={basket.toggle} focusedId={focusedResult?.id} focusedRef={focusedRef} isSeen={isSeen} />)}</div> :
              <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${effectiveCols}, minmax(0, 1fr))` }}>
                {gridResults.map((r, index) => (
                  <div key={r.id} ref={index === focusedIndex ? focusedRef : null} className="cv-auto">
                    <ResultItem
                      result={r}
                      onVideoClick={openVideo}
                      onImageClick={openImageForResult}
                      onFramesClick={openFrames}
                      basketRank={basket.rankOf(r.id)}
                      basketQuestion={basket.questionOf(r.id)}
                      currentQuestion={basket.current}
                      onToggleBasket={basket.toggle}
                      focused={index === focusedIndex}
                      seen={isSeen(r.id)}
                      onDupesClick={setDupeGroup}
                    />
                  </div>
                ))}
              </div>
            )}
          </div>
        </main>
      </div>

      {selectedVideo && (
        <VideoPlayerModal
          videoData={selectedVideo}
          onClose={closeVideo}
          pick={pickState}
          onPickFrame={pickState ? (idx) => basket.setFrame(pickState.id, idx, pickState.qid) : undefined}
        />
      )}

      {dupeGroup && (
        <DuplicateGroupModal
          group={dupeGroup}
          onClose={() => setDupeGroup(null)}
          onVideoClick={(f) => { setDupeGroup(null); openVideo(f); }}
          onFramesClick={(f) => { setDupeGroup(null); openFrames(f); }}
          basket={basket}
          isSeen={isSeen}
        />
      )}

      {frameSequence && (
        <FrameSequenceModal
          frame={frameSequence}
          onClose={() => setFrameSequence(null)}
          onVideoClick={(f) => { setFrameSequence(null); openVideo(f); }}
          basket={basket}
          isSeen={isSeen}
        />
      )}

      {/* Gallery dùng chung cho mọi loại truy vấn */}
      <ResultGallery
        results={galleryResults}
        open={openLightbox}
        index={currentImageIndex}
        onClose={() => setOpenLightbox(false)}
        onIndexChange={(i) => {
          setCurrentImageIndex(i);
          const r = galleryResults[i];
          if (r) {
            markSeen(r.id);
            // Giữ ô đang focus của lưới khớp với ảnh đang xem, để đóng gallery
            // ra là con trỏ bàn phím đứng đúng chỗ.
            const idx = indexByIdRef.current.get(r.id);
            if (idx != null) setFocusedIndex(idx);
          }
        }}
        onVideoClick={openVideo}
        onFramesClick={openFrames}
        onToggleBasket={basket.toggle}
        basketRankOf={basket.rankOf}
        currentQuestion={basket.current}
      />

      {/* Câu đang trả lời - pill nổi góc dưới-phải. Ẩn khi khay nộp bài mở:
          rail trong khay đã cho biết đang ở câu nào, hai chỗ cùng nói một
          chuyện thì chỉ tổ nhiễu. */}
      {!isSubmitOpen && (
        <QuestionSwitcher
          basket={basket}
          isOpen={isQuestionOpen}
          onToggle={() => setIsQuestionOpen((v) => !v)}
          onClose={() => setIsQuestionOpen(false)}
          onOpenBasket={() => { setIsQuestionOpen(false); setIsSubmitOpen(true); }}
        />
      )}

      <SubmissionPanel
        isOpen={isSubmitOpen}
        onClose={() => setIsSubmitOpen(false)}
        basket={basket}
        onFeedback={handleFeedbackSearch}
        feedbackLoading={feedbackLoading}
        onVideoClick={openVideo}
        onFramesClick={openFrames}
        onPickFrame={openVideoForPick}
        room={room}
        sheetOpen={isSheetOpen}
        setSheetOpen={setIsSheetOpen}
        csvOpen={isCsvPreviewOpen}
        setCsvOpen={setIsCsvPreviewOpen}
      />

      <RoomJoinModal isOpen={room.needsJoin} onJoin={room.join} onSkip={room.leave} />
      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        room={room}
        dedup={{
          enabled: dedup,
          setEnabled: setDedup,
          threshold: dedupThreshold,
          setThreshold: setDedupThreshold,
          // Ngưỡng chỉ có hiệu lực ở lượt search tiếp theo — cho bấm tìm lại ngay
          // tại đây, nếu không thì hiệu chỉnh phải đóng hộp thoại rồi bấm tìm.
          onRerun: hasSearched ? handleSearch : null,
        }}
      />
      <HotkeysHelp isOpen={isHelpOpen} onClose={() => setIsHelpOpen(false)} />
    </div>
  );
}

export default SearchPage;
