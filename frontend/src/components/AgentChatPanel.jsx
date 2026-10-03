// src/components/AgentChatPanel.jsx
// Panel trợ lý (MemoriEase-style): MỘT ô nhập cho cả ba dạng đề.
//   POST /agent/ask -> backend nhận dạng kis / qa / trake rồi gọi đúng đường:
//     kis   : plan + search (kém -> ReAct)          -> lưới frame
//     trake : plan + search_temporal                -> nhóm theo video
//     qa    : retrieve đa kênh + Gemini vision      -> câu trả lời + frame bằng chứng
// Dạng lấy từ bộ đề BTC (basket.taskType) khi đã nạp gói truy vấn, không thì
// backend đọc chính câu đề mà đoán; ô chọn dạng ở header cho phép ép tay.
// Kết quả đổ vào lưới chính qua onResults(list, type).
// Nhúng trong tab "Agent" của sidebar trái; isOpen chỉ ẩn/hiện bằng CSS để giữ lịch sử chat.
//
// LỊCH SỬ TRA CỨU (riêng từng người, lưu ở backend theo member_id):
// mỗi lượt chạy xong được lưu KÈM danh sách frame, nên mở lại một cuộc cũ và
// bấm "Xem lại kết quả" là đổ thẳng frame cũ vào lưới - KHÔNG gọi /agent/* lần
// nào, tức không tốn thêm lượt LLM. Đó là cả lý do tính năng này tồn tại: giữa
// buổi thi, gõ lại một hướng đã dò chỉ để nhìn lại frame là đốt quota key.
// Xem thêm hooks/useAgentChats.js và backend/services/agent_history_store.py.
import { useEffect, useRef, useState } from "react";
import { agentAsk } from "../api/searchService";
import { getLlmState } from "../api/llmStatus";
import { useAgentChats } from "../hooks/useAgentChats";
import {
  SparklesIcon, RefreshIcon, SendIcon, CheckIcon, ChevronDownIcon,
  ClockIcon, TrashIcon, ChevronLeftIcon,
} from "./Icons";

// Bản nháp cuộc đang dở, giữ trên MÁY NÀY. Cùng tinh thần "backend chết không
// được làm app ngưng dùng được" ghi ở đầu api/roomClient.js: tắt phòng, mất
// mạng hay F5 giữa lúc thi thì mạch hội thoại vẫn phải còn.
//
// Nháp cố tình KHÔNG chứa frame: một lượt top_k=200 nặng ~70KB, ghi vào
// localStorage mỗi lần gõ là đầy quota trong vài lượt. Frame nằm ở server, và
// lúc mở lại trang thì hydrate() kéo về (một GET, 0 token).
const DRAFT_KEY = "aic.agentchat.draft";

const WELCOME = {
  role: "assistant",
  content: "Dán nguyên đề vào đây - tìm cảnh (KIS), chuỗi cảnh (TRAKE) hay câu hỏi (Q&A) đều một ô này. "
    + "Có thể bổ sung qua nhiều lượt.",
  plan: null,
};

// Nhãn ba dạng đề của cuộc thi. "" = để backend tự nhận dạng từ câu đề.
const TASK_LABEL = { kis: "KIS", trake: "TRAKE", qa: "Q&A" };
const TASK_OPTIONS = [
  { value: "", label: "Tự nhận dạng", hint: "Theo bộ đề đã nạp, không có thì backend đoán" },
  { value: "kis", label: "KIS", hint: "Tìm 1 cảnh" },
  { value: "trake", label: "TRAKE", hint: "Chuỗi cảnh trong cùng video" },
  { value: "qa", label: "Q&A", hint: "Trả lời câu hỏi + frame bằng chứng" },
];

const newId = () =>
  crypto.randomUUID?.() ?? `t-${Date.now()}-${Math.random().toString(16).slice(2)}`;

function readDraft() {
  try {
    const raw = localStorage.getItem(DRAFT_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

/** Bỏ payload frame trước khi ghi nháp - xem ghi chú ở DRAFT_KEY. */
const lighten = (msg) =>
  msg.turn ? { ...msg, turn: { ...msg.turn, results: [], videos: [] } } : msg;

/** Cuộc trò chuyện từ server -> danh sách message của panel. */
function messagesFromChat(chat) {
  const out = [WELCOME];
  for (const t of chat.turns || []) {
    out.push({ role: "user", content: t.question });
    out.push({ role: "assistant", content: t.reply, plan: t.plan, trace: t.trace, turn: t });
  }
  return out;
}

function dayLabel(ts) {
  const d = new Date(ts || 0);
  const now = new Date();
  const sameDay = (a, b) => a.toDateString() === b.toDateString();
  if (sameDay(d, now)) return "Hôm nay";
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  if (sameDay(d, yesterday)) return "Hôm qua";
  return d.toLocaleDateString("vi-VN");
}

const hhmm = (ts) =>
  new Date(ts || 0).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });

// "timeout of 60000ms exceeded" không nói được cho ai điều gì hữu ích. Ba lỗi
// hay gặp nhất khi chạy backend trên Colab qua ngrok đều cần một hành động KHÁC
// nhau, nên phải tách rõ.
function errorText(err) {
  const detail = err.response?.data?.detail;
  if (detail) return detail;

  const quota = getLlmState();
  const quotaNote = quota.exhausted
    ? ` Key ${quota.provider} đang hết lượt truy cập - mỗi lần gọi LLM còn phải chờ retry, đó có thể là lý do chậm.`
    : "";

  if (err.code === "ECONNABORTED" || err.code === "ETIMEDOUT" || /timeout/i.test(err.message || "")) {
    return (
      "Quá thời gian chờ. Backend VẪN đang chạy tiếp ở phía kia - thử lại sau ít phút, " +
      "hoặc tắt Deep / giảm top-k cho nhẹ. Lần chạy đầu sau khi bật server còn phải nạp model (~10 phút)."
      + quotaNote
    );
  }
  if (err.code === "ERR_NETWORK") {
    return "Không nối được backend. Kiểm tra URL trong Cài đặt (URL ngrok đổi theo mỗi phiên) và xem server còn sống không.";
  }
  return (err.message || "Có lỗi xảy ra.") + quotaNote;
}

// Các bước ReAct - thu gọn dưới câu trả lời
const ReactTrace = ({ trace }) => {
  const [open, setOpen] = useState(false);
  if (!trace?.length) return null;
  return (
    <div className="mt-1.5">
      <button onClick={() => setOpen((v) => !v)} className="text-[11px] font-medium text-purple-600 hover:text-purple-700">
        ReAct: {trace.length} bước {open ? "▴" : "▾"}
      </button>
      {open && (
        <ol className="mt-1 space-y-1 text-[11px] text-slate-500 list-decimal list-inside">
          {trace.map((t, i) => (
            <li key={i}>
              {t.thought}
              {t.action && <span className="text-slate-400"> → {t.action.tool}</span>}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
};

/**
 * Dạng đề đã dùng cho lượt này. Phải hiện, không được xử lý ngầm: nếu máy nhận
 * dạng sai (đề KIS mà đọc thành Q&A) thì người thi cần thấy ngay để ép tay lại,
 * chứ không phải ngồi đoán vì sao kết quả kỳ cục.
 */
const TaskChip = ({ task }) => {
  if (!task?.type) return null;
  const auto = task.source !== "explicit";
  return (
    <div className="mt-1.5">
      <span
        title={task.reason || ""}
        className={`inline-block text-[11px] px-2 py-0.5 rounded-full font-semibold ${
          auto ? "bg-amber-100 text-amber-700" : "bg-blue-100 text-blue-700"
        }`}
      >
        {TASK_LABEL[task.type] || task.type}{auto ? " · tự nhận dạng" : " · theo bộ đề"}
      </span>
    </div>
  );
};

const PlanChips = ({ plan }) => {
  if (!plan) return null;
  const chips = [];
  if (plan.mode === "temporal") chips.push(`temporal: ${plan.events.join(" → ")}`);
  else if (plan.steps?.length >= 2) plan.steps.forEach((s) => chips.push(`${s.channel}: ${s.query}`));
  else if (plan.query) chips.push(plan.query);
  if (plan.objects) chips.push(`objects: ${plan.objects}`);
  if (plan.scene_keywords) chips.push(`scene: ${plan.scene_keywords}`);
  return (
    <div className="flex flex-wrap gap-1 mt-1.5">
      {chips.map((c, i) => (
        <span key={i} className="text-[11px] bg-slate-200 text-slate-600 px-2 py-0.5 rounded-full">{c}</span>
      ))}
    </div>
  );
};

/**
 * Đổ lại kết quả của một lượt vào lưới chính. KHÔNG gọi API nào - đây chính là
 * chỗ tiết kiệm token của cả tính năng.
 */
const ReplayResults = ({ turn, onResults }) => {
  if (!turn) return null;
  const list = turn.result_type === "temporal" ? turn.videos : turn.results;
  if (list?.length) {
    return (
      <button
        onClick={() => onResults(list, turn.result_type || "grid")}
        title="Đổ lại đúng kết quả của lượt này vào lưới - không tra lại, không tốn lượt LLM"
        className="mt-1.5 inline-flex items-center gap-1 text-[11px] font-semibold text-blue-600 hover:text-blue-700 hover:underline"
      >
        <RefreshIcon className="w-3 h-3" /> Xem lại kết quả ({list.length})
      </button>
    );
  }
  if (turn.trimmed) {
    return (
      <p className="mt-1.5 text-[11px] text-slate-400 italic">
        Frame của lượt này đã được dọn để nhường chỗ cho lượt mới — phải chạy lại nếu cần.
      </p>
    );
  }
  return null;
};

/**
 * Ô chọn dạng đề ở header. Dùng dropdown tự vẽ thay cho <select> hệ thống vì
 * cần khoe hai thông tin cùng lúc mà <option> không kham nổi: đang ở chế độ nào
 * và dạng nào đang thực sự được dùng (huy hiệu KIS/QA/TRAKE). Giữa buổi thi
 * người chạy chỉ liếc một cái - nhận dạng sai mà không thấy là mất lượt.
 *
 * `value` = ép tay ("" là để tự nhận dạng), `detected` = dạng từ bộ đề/backend.
 */
function TaskPicker({ value, detected, onChange }) {
  const [open, setOpen] = useState(false);
  const boxRef = useRef(null);

  // Bấm ra ngoài / Esc thì đóng - dropdown tự vẽ nên phải tự lo phần này.
  useEffect(() => {
    if (!open) return;
    const onDown = (e) => { if (!boxRef.current?.contains(e.target)) setOpen(false); };
    const onKey = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const auto = value === "";
  const current = TASK_OPTIONS.find((o) => o.value === value) || TASK_OPTIONS[0];
  const badge = auto ? (detected ? TASK_LABEL[detected] || detected : null) : TASK_LABEL[value];

  return (
    <div ref={boxRef} className="relative flex-1 min-w-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        title="Dạng đề. Tự nhận dạng = theo bộ đề đã nạp, không có thì backend đọc câu đề mà đoán."
        className={`w-full flex items-center gap-2 rounded-xl border px-2.5 py-1.5 text-left transition-colors ${
          auto
            ? "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"
            : "border-blue-200 bg-blue-50/70 hover:bg-blue-50"
        } ${open ? "ring-2 ring-blue-500/25 border-blue-300" : ""}`}
      >
        <SparklesIcon className={`w-4 h-4 shrink-0 ${auto ? "text-blue-500" : "text-blue-600"}`} />
        <span className="min-w-0 flex-1 truncate text-xs font-semibold text-slate-700">
          {current.label}
        </span>
        {badge && (
          <span
            className={`shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-bold tracking-wide ${
              auto ? "bg-slate-100 text-slate-500" : "bg-blue-600 text-white"
            }`}
            title={auto ? "Dạng máy nhận ra" : "Dạng bạn ép tay"}
          >
            {badge}
          </span>
        )}
        <ChevronDownIcon
          className={`w-3.5 h-3.5 shrink-0 text-slate-400 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <ul
          role="listbox"
          className="absolute left-0 right-0 top-full z-30 mt-1 overflow-hidden rounded-xl border border-slate-200 bg-white py-1 shadow-lg shadow-slate-900/10"
        >
          {TASK_OPTIONS.map((o) => {
            const active = o.value === value;
            return (
              <li key={o.value}>
                <button
                  type="button"
                  role="option"
                  aria-selected={active}
                  onClick={() => { onChange(o.value); setOpen(false); }}
                  className={`flex w-full items-start gap-2 px-2.5 py-1.5 text-left transition-colors ${
                    active ? "bg-blue-50" : "hover:bg-slate-50"
                  }`}
                >
                  <CheckIcon
                    className={`mt-0.5 w-3.5 h-3.5 shrink-0 ${active ? "text-blue-600" : "text-transparent"}`}
                  />
                  <span className="min-w-0">
                    <span className={`block text-xs font-semibold ${active ? "text-blue-700" : "text-slate-700"}`}>
                      {o.label}
                      {o.value === "" && detected && (
                        <span className="ml-1.5 font-medium text-slate-400">
                          → {TASK_LABEL[detected] || detected}
                        </span>
                      )}
                    </span>
                    <span className="block text-[10px] leading-snug text-slate-400">{o.hint}</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function AgentChatPanel({ isOpen, model, topK, selectedIds, currentQuestion, taskType,
                          onResults, inputRef, roomActive }) {
  // "" = theo bộ đề (prop taskType) hoặc để backend tự nhận dạng; khác "" =
  // người dùng ép tay dạng cho các lượt sau.
  const [taskOverride, setTaskOverride] = useState("");
  const [deep, setDeep] = useState(false);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState("chat");   // chat | history
  const [openingId, setOpeningId] = useState(null);

  // Nháp đọc đúng MỘT lần lúc mount (useState lazy), rồi hai state dưới ăn theo.
  const [boot] = useState(readDraft);
  const [chatId, setChatId] = useState(() => boot?.chatId || null);
  const [messages, setMessages] = useState(() =>
    boot?.messages?.length ? boot.messages : [WELCOME]);

  const { chats, loading, error, refresh, loadChat, saveTurn, removeChat, clearAll } =
    useAgentChats(roomActive);
  const bottomRef = useRef(null);

  // Ghi nháp mỗi khi mạch hội thoại đổi.
  useEffect(() => {
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify({
        chatId, messages: messages.map(lighten),
      }));
    } catch {
      // localStorage đầy/bị chặn -> phiên này vẫn chạy, chỉ là không sống qua F5
    }
  }, [chatId, messages]);

  // Vừa F5: nháp có mạch hội thoại nhưng KHÔNG có frame (cố ý, xem DRAFT_KEY).
  // Kéo bản đầy đủ từ phòng về đúng một lần để nút "Xem lại kết quả" dùng được
  // ngay - một GET metadata, không đụng /agent/*.
  const hydrated = useRef(false);
  useEffect(() => {
    if (hydrated.current || !roomActive || !chatId) return;
    if (messages.some((m) => m.turn?.results?.length || m.turn?.videos?.length)) {
      hydrated.current = true;   // frame còn trong RAM -> đừng đụng vào
      return;
    }
    hydrated.current = true;
    loadChat(chatId).then((chat) => {
      if (chat?.turns?.length) setMessages(messagesFromChat(chat));
    });
  }, [roomActive, chatId, messages, loadChat]);

  useEffect(() => {
    if (view === "chat") bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isOpen, view]);

  const newChat = () => {
    if (busy) return;
    setChatId(null);
    setMessages([WELCOME]);
    setInput("");
    setView("chat");
  };

  const openHistory = () => {
    setView("history");
    refresh();
  };

  const openChat = async (id) => {
    if (busy || openingId) return;
    setOpeningId(id);
    const chat = await loadChat(id);
    setOpeningId(null);
    if (!chat) return;
    hydrated.current = true;   // vừa nạp tay -> đừng để effect hydrate đè lên
    setChatId(chat.id);
    setMessages(messagesFromChat(chat));
    setView("chat");
  };

  const dropChat = (e, id) => {
    e.stopPropagation();
    removeChat(id);
    // Đang mở đúng cuộc vừa xoá -> bắt đầu cuộc mới, không để mạch hội thoại
    // trỏ vào một cuộc không còn trên server (lượt sau sẽ tạo lại nó).
    if (id === chatId) {
      setChatId(null);
      setMessages([WELCOME]);
    }
  };

  // Dạng gửi lên backend: ép tay > dạng của câu đang làm (chỉ có khi đã nạp bộ
  // đề) > "" để backend tự đọc câu đề mà nhận dạng.
  const askTask = taskOverride || taskType || "";

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    const id = chatId || newId();
    if (!chatId) setChatId(id);
    const nextMessages = [...messages, { role: "user", content: text }];
    setMessages(nextMessages);
    setBusy(true);
    try {
      const history = nextMessages.map(({ role, content }) => ({ role, content }));
      // rerank ĐI KÈM deep, không phải lựa chọn độc lập. Đo trên
      // backend/eval/sotuyen12.json, 55 câu:
      //   deep=false: rerank tắt 16.2 vs bật 17.5 @1 - hoà, mà tắt nhanh hơn
      //               3.2 giây/câu -> tắt.
      //   deep=true : rerank tắt 14.5 vs bật 22.5 @1, @100 43.0 vs 51.0 -> BẬT.
      // Lý do: react_refine so results[0].score với best_score để quyết ghép
      // danh sách. Không rerank thì hai bên cùng thang điểm fusion, search một
      // kênh của ReAct thắng quá dễ và đè mất fan-out. Bật deep mà tắt rerank
      // còn TỆ HƠN không bật deep.
      const data = await agentAsk(history, {
        taskType: askTask, frameIds: selectedIds, topK, model, rerank: deep, deep,
      });
      const isQa = data.task_type === "qa";
      const temporal = !isQa && (data.videos || []).length > 0;
      const list = temporal ? data.videos : (data.results || []);
      // QA: nói rõ câu trả lời dựa trên frame nào - người thi phải kiểm được.
      const note = !isQa ? ""
        : selectedIds?.length
          ? ` (dựa trên ${selectedIds.length} frame trong giỏ câu ${currentQuestion})`
          : " (tự tìm frame liên quan)";
      const content = `${data.reply}${note}`;
      const turn = {
        // `mode` là trường lịch sử lưu được ở server (AgentTurn) - dùng luôn nó
        // để giữ dạng đề, khỏi phải đổi schema phòng thi.
        id: newId(), ts: Date.now(), mode: data.task_type, question: text,
        reply: content, plan: data.plan || null, trace: data.trace || [],
        result_type: temporal ? "temporal" : "grid",
        results: temporal ? [] : list,
        videos: temporal ? list : [],
      };
      setMessages((m) => [...m, {
        role: "assistant", content, plan: data.plan || null, trace: data.trace,
        task: { type: data.task_type, source: data.task_source, reason: data.task_reason },
        turn,
      }]);
      onResults(list, temporal ? "temporal" : "grid");
      // Tiêu đề cuộc = câu hỏi ĐẦU TIÊN (WELCOME là role assistant nên không lọt).
      const title = nextMessages.find((m) => m.role === "user")?.content || text;
      saveTurn(id, title, turn);
    } catch (err) {
      setMessages((m) => [...m, { role: "assistant", content: errorText(err), plan: null, isError: true }]);
    } finally {
      setBusy(false);
    }
  };

  // Nhóm theo ngày - lịch sử một buổi thi dài, mốc "Hôm nay / Hôm qua" là cách
  // nhanh nhất để tìm lại hướng vừa dò.
  let lastDay = null;

  return (
    <div className={`${isOpen ? "flex" : "hidden"} flex-col flex-1 min-h-0 bg-white text-slate-800`}>
      {/* Header: chuyển chế độ + lịch sử + cuộc trò chuyện mới */}
      <div className="flex items-center gap-2 px-4 py-3 shrink-0">
        {view === "history" ? (
          <button
            onClick={() => setView("chat")}
            className="flex-1 inline-flex items-center gap-1.5 text-sm font-semibold text-slate-600 hover:text-slate-900"
          >
            <ChevronLeftIcon className="w-4 h-4" /> Lịch sử tra cứu
          </button>
        ) : (
          /* Một ô nhập cho cả ba dạng -> chỗ này không còn là công tắc bắt buộc
             bấm, chỉ là nút ép tay khi máy đoán sai. */
          <TaskPicker value={taskOverride} detected={taskType} onChange={setTaskOverride} />
        )}
        {/* Vạch ngăn: bên trái là "chạy cái gì", bên phải là thao tác phiên. */}
        <span className="w-px h-5 bg-slate-200 shrink-0" />
        {view === "chat" ? (
          <>
            <button onClick={openHistory} title="Lịch sử tra cứu (xem lại không tốn lượt LLM)"
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors">
              <ClockIcon className="w-4 h-4" />
            </button>
            <button onClick={newChat} disabled={busy} title="Cuộc trò chuyện mới"
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 disabled:opacity-40 transition-colors">
              <RefreshIcon className="w-4 h-4" />
            </button>
          </>
        ) : (
          <button onClick={refresh} disabled={loading} title="Nạp lại danh sách"
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 disabled:opacity-40 transition-colors">
            <RefreshIcon className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* ===== DANH SÁCH LỊCH SỬ ===== */}
      {view === "history" && (
        <div className="flex-1 px-4 py-2 overflow-y-auto text-sm">
          {!roomActive && (
            <p className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-2 mb-2">
              Đang tắt chế độ phòng nên lịch sử không được lưu lên server — cuộc đang dở vẫn
              giữ trên máy này qua F5. Bật phòng ở Cài đặt (⚙) để lưu lại và xem lại về sau.
            </p>
          )}
          {error && (
            <p className="text-[11px] text-red-700 bg-red-50 border border-red-200 rounded-lg p-2 mb-2">{error}</p>
          )}
          {loading && <p className="text-xs text-slate-400 animate-pulse">Đang nạp…</p>}
          {!loading && roomActive && !chats.length && !error && (
            <p className="text-xs text-slate-400">
              Chưa có cuộc nào. Mỗi lượt hỏi Agent sẽ tự được lưu kèm kết quả để xem lại sau.
            </p>
          )}
          <ul className="space-y-1">
            {chats.map((c) => {
              const day = dayLabel(c.updated_at);
              const showDay = day !== lastDay;
              lastDay = day;
              return (
                <li key={c.id}>
                  {showDay && (
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400 mt-3 mb-1">{day}</p>
                  )}
                  <div
                    role="button"
                    tabIndex={0}
                    onClick={() => openChat(c.id)}
                    onKeyDown={(e) => { if (e.key === "Enter") openChat(c.id); }}
                    className={`group w-full flex items-center gap-2 text-left bg-white border rounded-lg px-2 py-1.5 cursor-pointer transition ${
                      c.id === chatId ? "border-blue-300 bg-blue-50" : "border-slate-200 hover:border-blue-300 hover:bg-blue-50"
                    }`}
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium text-slate-700 truncate" title={c.title}>
                        {c.title || "(không tiêu đề)"}
                      </p>
                      <p className="text-[10px] text-slate-400 tabular-nums">
                        {hhmm(c.updated_at)} · {c.turn_count} lượt
                        {c.result_count > 0 && <> · {c.result_count} frame</>}
                        {openingId === c.id && <span className="text-blue-500"> · đang mở…</span>}
                      </p>
                    </div>
                    <button
                      onClick={(e) => dropChat(e, c.id)}
                      title="Xoá cuộc này"
                      className="shrink-0 p-1 rounded text-slate-300 opacity-0 group-hover:opacity-100 hover:text-red-600 hover:bg-red-50 transition"
                    >
                      <TrashIcon className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
          {chats.length > 0 && (
            <button
              onClick={clearAll}
              className="mt-3 text-[11px] text-slate-400 hover:text-red-600"
            >
              Xoá toàn bộ lịch sử của tôi
            </button>
          )}
        </div>
      )}

      {/* ===== HỘI THOẠI ===== */}
      {/* Ẩn bằng CSS chứ không unmount: mở tab Lịch sử rồi quay lại phải thấy
          nguyên cuộc đang gõ dở, kể cả ô nhập. */}
      <div className={`${view === "chat" ? "flex" : "hidden"} flex-col flex-1 min-h-0`}>
        {/* Messages - px-4 để thẳng hàng với header phía trên và với tab Thủ công */}
        <div className="flex-1 px-4 py-3 overflow-y-auto space-y-2 text-sm">
          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
              <div className={`p-2.5 rounded-lg max-w-[85%] whitespace-pre-wrap break-words ${
                msg.role === "user" ? "bg-blue-600 text-white" : msg.isError ? "bg-red-50 text-red-700 border border-red-200" : "bg-slate-100 text-slate-700"
              }`}>
                {msg.content}
                <TaskChip task={msg.task} />
                <PlanChips plan={msg.plan} />
                <ReactTrace trace={msg.trace} />
                <ReplayResults turn={msg.turn} onResults={onResults} />
              </div>
            </div>
          ))}
          {busy && (
            <div className="flex justify-start">
              <div className="p-2.5 rounded-lg bg-slate-100 text-slate-400 animate-pulse">
                {askTask === "qa" ? "Đang xem frame & trả lời…"
                  : askTask ? "Đang lên plan & tìm kiếm…"
                    : "Đang nhận dạng đề & tìm kiếm…"}
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Composer: ô nhập + hàng tuỳ chọn cho lượt gửi (Deep) + nút gửi */}
        <div className="px-4 py-3 shrink-0 border-t border-slate-200 bg-white">
          <div className={`rounded-2xl border bg-white transition-colors ${
            deep && askTask !== "qa"
              ? "border-purple-300 focus-within:ring-2 focus-within:ring-purple-500/20"
              : "border-slate-300 focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-500/20"
          }`}>
            <textarea
              ref={inputRef}
              rows={2}
              placeholder={askTask === "qa" ? "Đặt câu hỏi về nội dung video…"
                : "Dán đề vào đây - mô tả cảnh, chuỗi cảnh hoặc câu hỏi…"}
              className="w-full px-3 pt-2.5 pb-1 bg-transparent border-0 resize-none text-sm text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-0 max-h-40"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
              }}
              disabled={busy}
            />
            <div className="flex items-center justify-between gap-2 px-2 pb-2">
              {askTask === "qa" ? (
                <span className="pl-1.5 text-[11px] text-slate-400 truncate">
                  {selectedIds?.length ? `Dựa trên ${selectedIds.length} frame trong giỏ câu ${currentQuestion}` : "Tự tìm frame liên quan"}
                </span>
              ) : (
                <button
                  onClick={() => setDeep((v) => !v)}
                  aria-pressed={deep}
                  title="Deep: ép chạy vòng ReAct - lên plan nhiều bước, chậm hơn nhưng kỹ hơn. Đề Q&A không dùng."
                  className={`inline-flex items-center gap-1.5 pl-2 pr-2.5 py-1.5 rounded-full text-xs font-semibold border transition-colors ${
                    deep
                      ? "border-purple-200 bg-purple-50 text-purple-700 hover:bg-purple-100"
                      : "border-slate-200 text-slate-500 hover:bg-slate-50 hover:text-slate-700"
                  }`}
                >
                  <SparklesIcon className="w-3.5 h-3.5" /> Deep
                </button>
              )}
              <button
                onClick={send}
                disabled={busy || !input.trim()}
                title="Gửi (Enter)"
                className="shrink-0 w-8 h-8 flex items-center justify-center rounded-full bg-blue-600 text-white hover:bg-blue-700 disabled:bg-slate-200 disabled:text-slate-400 transition-colors"
              >
                <SendIcon className="w-4 h-4" />
              </button>
            </div>
          </div>
          <p className="mt-1.5 text-[11px] text-slate-400">
            {deep && askTask !== "qa"
              ? "Deep đang bật - agent sẽ chạy vòng ReAct nhiều bước."
              : "Enter để gửi · Shift+Enter xuống dòng"}
          </p>
        </div>
      </div>
    </div>
  );
}

export default AgentChatPanel;
