// src/api/roomClient.js
// Kết nối tới phòng thi nhóm: WebSocket nhận, REST gửi.
//
// NGUYÊN TẮC SỐ MỘT: backend chết KHÔNG được làm app ngưng dùng được. Đang thi
// mà mất mạng vài phút vẫn phải tìm và chốt đáp án tiếp được, rồi tự đồng bộ khi
// mạng về. Nên:
//   - localStorage vẫn là bản sao bền vững (useAnswerBasket luôn ghi);
//   - op gửi đi xếp vào MỘT hàng đợi có thứ tự, mất mạng thì nằm chờ ở đó
//     (mirror sang localStorage để đóng tab cũng không mất);
//   - mạng về: xả hàng đợi TUẦN TỰ trước, rồi mới nhận state server.
//
// Vì sao hàng đợi tuần tự chứ không bắn song song: op của giỏ phụ thuộc thứ tự
// (thêm f1 rồi move nó lên đầu). Bắn song song mà một cái lỗi phải thử lại thì
// server nhận sai thứ tự -> thứ tự nộp bài sai.
import axios from "axios";
import { resolveBaseUrl, subscribeBaseUrl, TUNNEL_HEADERS } from "./apiClient";

const PENDING_KEY = "aic.room.pending";
const MEMBER_KEY = "aic.member";
const ENABLED_KEY = "aic.roomEnabled";
// Base URL của RIÊNG phòng, tách khỏi `aic.apiBase` của apiClient. Xem
// resolveRoomBaseUrl() bên dưới về việc vì sao cần tách.
const ROOM_BASE_KEY = "aic.roomBase";

// Trần backoff 5s: phòng thi tính giờ, chờ lâu hơn là mất việc.
const BACKOFF_MS = [500, 1000, 2000, 3000, 5000];

// Nhịp ping và hạn im lặng. Ba nhịp không nghe gì (kể cả pong) = socket đã chết,
// dù trình duyệt vẫn báo OPEN.
//
// 90s chứ không phải 60s: hạn cũ rộng hơn hai nhịp ping đúng bằng KHÔNG, nên chỉ
// cần một pong về trễ nửa giây là client tự giết một socket đang sống. Phía
// server dùng STALE_MS (room_hub.py) và con số đó phải luôn RỘNG HƠN chỗ này,
// nếu không server đá người ra trước khi client kịp nhận ra.
const PING_MS = 25000;
const PONG_TIMEOUT_MS = 90000;
// Tab vừa sáng lại thì hỏi một câu và chỉ chờ chừng này. Lúc đó có người đang
// ngồi nhìn màn hình nên phải biết nhanh, không kéo dài như hạn ở trên.
const WAKE_PROBE_MS = 5000;

function readJSON(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function writeJSON(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // localStorage đầy/bị chặn -> hàng đợi vẫn chạy trong RAM
  }
}

// Tab đang bị che/thu nhỏ? Quan trọng vì mọi phép đo thời gian bằng setTimeout/
// setInterval ở tab ẩn đều KHÔNG đáng tin - xem ghi chú trong pingTimer.
function isHidden() {
  return typeof document !== "undefined" && document.visibilityState === "hidden";
}

export function readMember() {
  const m = readJSON(MEMBER_KEY, null);
  return m && m.id && m.name ? m : null;
}

export function saveMember(name) {
  const prev = readMember();
  const member = {
    id: prev?.id || (crypto.randomUUID?.() ?? `m-${Date.now()}-${Math.random().toString(16).slice(2)}`),
    name: String(name || "").trim() || "Ẩn danh",
  };
  writeJSON(MEMBER_KEY, member);
  return member;
}

/** Có đặt URL phòng RIÊNG không (localStorage hoặc .env)? */
export function hasOwnRoomBaseUrl() {
  return !!(readJSON(ROOM_BASE_KEY, null) || import.meta.env.VITE_ROOM_BASE_URL);
}

/**
 * Base URL của phòng. Ưu tiên: localStorage -> .env -> base URL của backend chính.
 *
 * Tách khỏi apiClient để mỗi người chạy được BACKEND RIÊNG (search trên máy mình,
 * dùng GPU của mình) mà vẫn chung MỘT giỏ đáp án: 5 người trỏ `apiBase` về 5 chỗ
 * khác nhau, nhưng cùng một `roomBase`.
 *
 * Trống thì rơi về apiBase, tức đúng hành vi trước khi có tuỳ chọn này - chế độ
 * LAN (một máy chạy cả BE lẫn FE) và chế độ một mình không phải cấu hình gì thêm.
 */
export function resolveRoomBaseUrl() {
  const stored = readJSON(ROOM_BASE_KEY, null);
  if (stored) return stored;
  return import.meta.env.VITE_ROOM_BASE_URL || resolveBaseUrl();
}

/**
 * URL phòng đang dùng ĐẾN TỪ ĐÂU. Ba nguồn của resolveRoomBaseUrl() sửa ở ba chỗ
 * hoàn toàn khác nhau, nên lúc mất kết nối mà chỉ in ra cái host thì vẫn không
 * biết phải đi sửa ở đâu - nhất là khi localStorage giữ một URL tunnel đã chết
 * và lặng lẽ ĐÈ LÊN .env vừa sửa xong.
 */
export function roomBaseSource() {
  if (readJSON(ROOM_BASE_KEY, null)) return "settings";
  if (import.meta.env.VITE_ROOM_BASE_URL) return "env";
  return "backend";
}

export function isRoomEnabled() {
  const v = readJSON(ENABLED_KEY, true);
  return v !== false;
}

export function setRoomEnabled(on) {
  writeJSON(ENABLED_KEY, !!on);
}

function wsUrl(base, member) {
  const http = base.replace(/\/+$/, "");
  const proto = http.startsWith("https:") ? "wss:" : "ws:";
  const rest = http.replace(/^https?:/, "");
  const q = new URLSearchParams({ member_id: member.id, member_name: member.name });
  return `${proto}${rest}/room/ws?${q}`;
}

function createRoomClient() {
  let ws = null;
  let member = null;
  let baseUrl = null;
  let started = false;
  let attempt = 0;
  let reconnectTimer = null;
  let pingTimer = null;
  let probeTimer = null;
  let draining = false;
  let drainAttempt = 0;
  let drainTimer = null;
  let lastMsgAt = 0;
  let queue = readJSON(PENDING_KEY, []) || [];

  const listeners = new Set();   // nhận message state (snapshot/question/meta/history/presence)
  const statusListeners = new Set();
  // everConnected: phân biệt "chưa nối lần nào" (mới mở app, đang bắt tay) với
  // "đã nối rồi và bị rớt". Chỉ trạng thái đầu mới hiện "Đang nối…"; rớt giữa
  // chừng thì giữ nguyên cảnh báo mất kết nối, không nhấp nháy qua lại theo
  // từng nhịp backoff.
  let status = { connected: false, connecting: false, everConnected: false, pending: queue.length, error: null };

  const emit = (msg) => listeners.forEach((fn) => fn(msg));

  // Chỉ phát khi thực sự có gì đổi. Mỗi op đi qua đây hai lần không mang tin gì
  // mới - setStatus({}) lúc xếp hàng và setStatus({error:null}) lúc gửi xong -
  // mà useRoom đổ thẳng vào React state, nên mỗi lần là một lượt render lại cả
  // SearchPage. Object mới thì useState luôn coi là đổi, phải tự so từng trường.
  function setStatus(patch) {
    const next = { ...status, ...patch, pending: queue.length };
    if (
      next.connected === status.connected &&
      next.connecting === status.connecting &&
      next.everConnected === status.everConnected &&
      next.pending === status.pending &&
      next.error === status.error
    ) return;
    status = next;
    statusListeners.forEach((fn) => fn(status));
  }

  // headers: xem TUNNEL_HEADERS trong apiClient - roomClient tự tạo axios riêng
  // nên không thừa hưởng default của apiClient.
  const http = () => axios.create({ baseURL: baseUrl, timeout: 8000, headers: { ...TUNNEL_HEADERS } });

  // --- Hàng đợi gửi --------------------------------------------------------
  function persistQueue() {
    writeJSON(PENDING_KEY, queue);
  }

  // Hàng đợi tắc thì phải TỰ thử lại: trước đây chỗ này gọi scheduleReconnect(),
  // tức lấy socket ra chữa bệnh của REST - socket đang sống vẫn bị mở thêm cái
  // nữa, rồi cái cũ đóng và báo "Offline" trong khi phòng vẫn chạy. Nay REST có
  // backoff riêng, không đụng tới socket.
  function scheduleDrain() {
    if (!started || drainTimer || !queue.length) return;
    const base = BACKOFF_MS[Math.min(drainAttempt, BACKOFF_MS.length - 1)];
    drainAttempt += 1;
    drainTimer = setTimeout(() => {
      drainTimer = null;
      drain();
    }, base + Math.random() * base * 0.3);
  }

  async function drain() {
    if (draining || !started || !baseUrl || !member) return;
    draining = true;
    const client = http();
    while (queue.length) {
      const job = queue[0];
      try {
        await client.post(job.path, { member_id: member.id, member_name: member.name, ...job.body });
        queue.shift();
        persistQueue();
        drainAttempt = 0;
        setStatus({ error: null });
      } catch (err) {
        // Server trả 4xx = op này sai (schema đổi, dữ liệu hỏng). Giữ lại thì
        // nó chặn vĩnh viễn mọi op phía sau -> bỏ và đi tiếp.
        const code = err?.response?.status;
        if (code && code >= 400 && code < 500) {
          console.warn("[room] op bị server từ chối, bỏ qua:", code, job);
          queue.shift();
          persistQueue();
          continue;
        }
        draining = false;
        setStatus({ error: "send" });
        scheduleDrain();
        return;
      }
    }
    draining = false;
    drainAttempt = 0;
    setStatus({ error: null });
  }

  function enqueue(path, body) {
    queue.push({ path, body });
    persistQueue();
    setStatus({});
    drain();
  }

  // --- WebSocket -----------------------------------------------------------
  // Đóng socket mà KHÔNG để onclose kích hoạt backoff. Dùng khi ta chủ động
  // ngắt (rời phòng, đổi backend) - nếu không, close() sẽ hẹn nối lại vào đúng
  // host vừa bị bỏ.
  function closeSocket() {
    // Probe thuộc về đúng một socket: socket đi thì probe cũng đi, không thì nó
    // nổ vào socket kế tiếp và đóng nhầm cái vừa mở.
    clearTimeout(probeTimer);
    probeTimer = null;
    if (!ws) return;
    ws.onopen = null;
    ws.onmessage = null;
    ws.onclose = null;
    ws.onerror = null;
    try { ws.close(); } catch { /* bỏ qua */ }
    ws = null;
  }

  const socketAlive = () =>
    !!ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING);

  function sendPing() {
    try {
      if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "ping" }));
    } catch { /* bỏ qua */ }
  }

  // Kết luận "socket đã chết": gỡ bỏ, báo trạng thái, hẹn nối lại.
  function declareDead() {
    clearInterval(pingTimer);
    closeSocket();
    setStatus({ connected: false, connecting: false, error: "offline" });
    scheduleReconnect();
  }

  // socketAlive: chặn việc mở socket thứ hai khi đã có một cái đang sống. Hai
  // socket cùng phòng thì mỗi message vào hai lần, và cái nào đóng trước cũng
  // kéo trạng thái về "Offline" dù cái kia vẫn đang nhận.
  function scheduleReconnect() {
    if (!started || reconnectTimer || socketAlive()) return;
    const base = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)];
    // Jitter: 5 máy mất mạng cùng lúc (rút dây switch) sẽ nối lại lệch nhau,
    // không dội cùng một nhịp vào backend.
    const delay = base + Math.random() * base * 0.3;
    attempt += 1;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      open();
    }, delay);
  }

  function open() {
    if (!started || !member || !baseUrl) return;
    closeSocket(); // bất biến: mỗi lúc chỉ có đúng một socket của phòng
    try {
      ws = new WebSocket(wsUrl(baseUrl, member));
      setStatus({ connecting: true });
    } catch (err) {
      console.warn("[room] không mở được WebSocket:", err);
      setStatus({ connecting: false });
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      attempt = 0;
      setStatus({ connected: true, connecting: false, everConnected: true, error: null });
      drain(); // mạng vừa về: đẩy hết việc tồn trước
      lastMsgAt = Date.now();
      clearInterval(pingTimer);
      // Giữ socket sống qua NAT/proxy hay im lặng cắt kết nối treo, ĐỒNG THỜI
      // canh chừng: rút dây/ngủ máy thì trình duyệt có thể giữ socket ở trạng
      // thái "open" hàng phút mà không tin nào tới. Không có đồng hồ này thì
      // thanh trạng thái báo Online trong khi phòng đã mất từ lâu.
      //
      // NHƯNG chỉ kết luận khi tab đang MỞ. Chrome bóp setInterval ở tab ẩn
      // xuống 1 lần/phút, nên ở tab nền phép đo dưới đây đo chính cái đồng hồ bị
      // bóp chứ không đo socket: nhịp ping giãn ra ~60s, hiệu "im lặng bao lâu"
      // chạm hạn, và client giết một socket hoàn toàn khoẻ mạnh - rồi setTimeout
      // hẹn nối lại cũng bị bóp nốt, nên badge nằm ở "Mất kết nối" hàng phút.
      // Ở tab nền cứ ping cho NAT khỏi cắt, còn việc kiểm tra để dành cho lúc
      // tab sáng lại (resume() bên dưới) - đằng nào lúc ẩn cũng không ai nhìn.
      pingTimer = setInterval(() => {
        if (!isHidden() && Date.now() - lastMsgAt > PONG_TIMEOUT_MS) {
          declareDead();
          return;
        }
        sendPing();
      }, PING_MS);
    };

    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      lastMsgAt = Date.now();
      if (msg.type === "pong") return;
      // Snapshot của server CHƯA có các op còn nằm trong hàng đợi. Đính kèm để
      // useAnswerBasket đắp lại lên trên, nếu không màn hình sẽ nháy mất việc
      // vừa làm offline rồi mới hiện lại sau khi xả hàng đợi.
      if (msg.type === "snapshot") msg.pending = queue.filter((j) => j.path === "/room/op").map((j) => j.body.op);
      emit(msg);
    };

    ws.onclose = () => {
      clearInterval(pingTimer);
      setStatus({ connected: false, connecting: false });
      scheduleReconnect();
    };

    ws.onerror = () => {
      // onclose luôn theo sau onerror -> để onclose lo việc nối lại.
      setStatus({ error: "offline" });
    };
  }

  /**
   * "Quay lại bàn": máy vừa có mạng lại, hoặc tab vừa sáng lên. Cả hai đều là
   * lúc phải cho kết quả NGAY, đừng ngồi hết cây backoff 5s - mà ở tab nền cây
   * backoff đó còn bị trình duyệt bóp thành hàng phút.
   *
   * Hai tình huống phải phân biệt:
   *   - socket đã đứt hẳn (server restart lúc mình đang xem tab khác) -> mở lại;
   *   - socket còn "OPEN" trên giấy tờ nhưng đã chết lặng (máy vừa ngủ dậy, NAT
   *     cắt ngang) -> hỏi một câu, WAKE_PROBE_MS không trả lời thì bỏ. Không có
   *     bước này thì phải đợi hết PONG_TIMEOUT_MS mới biết, tức 90s nhìn vào một
   *     chấm xanh nói dối.
   */
  function resume() {
    if (!started) return;
    attempt = 0;
    drainAttempt = 0;
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
    clearTimeout(drainTimer);
    drainTimer = null;

    if (!socketAlive()) {
      open();
    } else if (ws.readyState === WebSocket.OPEN) {
      const askedAt = Date.now();
      sendPing();
      clearTimeout(probeTimer);
      probeTimer = setTimeout(() => {
        probeTimer = null;
        if (lastMsgAt >= askedAt) return; // có tin về sau lúc hỏi -> socket sống
        declareDead();
      }, WAKE_PROBE_MS);
    }
    drain();
  }

  // Máy vừa có mạng lại (rút/cắm dây, Wi-Fi chập) thì nối NGAY. Ngược lại, mất
  // mạng thì báo liền thay vì đợi socket timeout.
  if (typeof window !== "undefined") {
    window.addEventListener("online", resume);
    // Tab sáng lại: đây là điểm kiểm tra thật sự của cả cơ chế trên, vì lúc ẩn
    // ta đã cố tình không kết luận gì. Guard `document` riêng: test chạy trên
    // node có thể dựng `window` giả mà không dựng `document`.
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", () => {
        if (!isHidden()) resume();
      });
    }
    window.addEventListener("offline", () => {
      if (!started) return;
      // Bỏ hẳn socket cũ: giữ lại thì nó nằm ở trạng thái "còn sống" giả, chặn
      // luôn lần nối lại sau. scheduleReconnect vẫn chạy để không phụ thuộc
      // hoàn toàn vào sự kiện "online" (có trình duyệt báo trễ hoặc không báo).
      declareDead();
    });
  }

  return {
    start(m) {
      member = m;
      baseUrl = resolveRoomBaseUrl();
      if (started) return;
      started = true;
      open();
      drain();
    },

    stop() {
      started = false;
      clearTimeout(reconnectTimer);
      clearTimeout(drainTimer);
      clearInterval(pingTimer);
      reconnectTimer = null;
      drainTimer = null;
      closeSocket();
      // everConnected về false: rời phòng rồi vào lại = bắt tay từ đầu.
      setStatus({ connected: false, connecting: false, everConnected: false, error: null });
    },

    /**
     * Host của phòng vừa đổi (Settings ⚙: ô Room URL, hoặc ô Backend URL khi
     * phòng đang ăn theo nó). REST thì axios tự đi đúng chỗ, nhưng WebSocket và
     * hàng đợi của phòng bám `baseUrl` chốt từ lúc start() nên phải dựng lại -
     * nếu không, phòng im lặng bám host cũ tới khi F5. Đây là thao tác làm mỗi
     * buổi ngrok vì URL tunnel đổi theo session.
     *
     * Hàng đợi pending KHÔNG bị đụng: op còn tồn vẫn phải được gửi, chỉ là gửi
     * sang host mới.
     */
    rebase(url) {
      const next = url || resolveRoomBaseUrl();
      if (!started || next === baseUrl) return;
      baseUrl = next;
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
      clearTimeout(drainTimer);
      drainTimer = null;
      clearInterval(pingTimer);
      closeSocket();
      attempt = 0;           // host mới -> chờ lại từ đầu, không kế thừa backoff
      drainAttempt = 0;
      draining = false;      // vòng drain cũ đã thoát khi request lỗi
      setStatus({ connected: false, connecting: false, error: null });
      open();
      drain();
    },

    get member() {
      return member;
    },

    sendOp(op) {
      if (!started) return;
      enqueue("/room/op", { op });
    },

    sendHistory(entry) {
      if (!started) return;
      enqueue("/room/history", entry);
    },

    // Một lượt tải zip nộp bài. Vào HÀNG ĐỢI như op: mất mạng đúng lúc bấm tải
    // mà con số này rơi mất thì cả phòng đếm hụt lượt. Server khử trùng theo id
    // nên gửi lại cũng không cộng thêm lượt.
    sendSubmitLog(entry) {
      if (!started) return;
      enqueue("/room/submitlog", entry);
    },

    // Xoá nhật ký nộp của cả phòng (đi kèm "tạo đề mới"). Cũng vào hàng đợi:
    // rơi mất thì lượt của vòng CŨ vẫn được đếm vào gói của vòng mới.
    clearSubmitLog() {
      if (!started) return;
      enqueue("/room/submitlog/clear", {});
    },

    // --- Lịch sử tra cứu Agent (RIÊNG từng người) --------------------------
    // Ghi thì vào HÀNG ĐỢI như op: mất mạng đúng lúc agent trả lời xong mà lượt
    // đó rơi mất là phải chạy lại /agent/chat, tức tốn đúng số token mà tính
    // năng này sinh ra để khỏi tốn. Server khử trùng theo turn.id nên xả lại
    // hàng đợi không nhân đôi lượt.
    sendAgentTurn(entry) {
      if (!started) return;
      enqueue("/room/agent_chats/turn", entry);
    },

    deleteAgentChat(chatId) {
      if (!started) return;
      enqueue("/room/agent_chats/delete", { chat_id: chatId || null });
    },

    // Đọc thì KHÔNG vào hàng đợi: đọc mà offline chẳng có nghĩa gì, và hàng đợi
    // là để không mất việc đã làm chứ không phải để thử lại một lượt xem.
    //
    // baseUrl/member lấy trực tiếp thay vì qua start(): panel Agent đọc được cả
    // khi người dùng chưa vào phòng - lịch sử là của riêng họ, không phụ thuộc
    // ai đang online.
    async fetchAgentChats(limit = 50) {
      const me = member || readMember();
      if (!me) return [];
      const client = axios.create({
        baseURL: baseUrl || resolveRoomBaseUrl(), timeout: 8000, headers: { ...TUNNEL_HEADERS },
      });
      const res = await client.get("/room/agent_chats", {
        params: { member_id: me.id, limit },
      });
      return res.data?.chats || [];
    },

    async fetchAgentChat(chatId) {
      const me = member || readMember();
      if (!me) return null;
      const client = axios.create({
        baseURL: baseUrl || resolveRoomBaseUrl(), timeout: 15000, headers: { ...TUNNEL_HEADERS },
      });
      const res = await client.get(`/room/agent_chats/${encodeURIComponent(chatId)}`, {
        params: { member_id: me.id },
      });
      return res.data || null;
    },

    // Đang mở câu mấy - tin vặt, mất cũng không sao nên KHÔNG vào hàng đợi.
    sendCurrent(current) {
      try {
        if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "presence", current }));
      } catch { /* bỏ qua */ }
    },

    subscribe(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },

    subscribeStatus(fn) {
      statusListeners.add(fn);
      fn(status);
      return () => statusListeners.delete(fn);
    },

    getStatus() {
      return status;
    },
  };
}

const roomClient = createRoomClient();

/**
 * Đổi URL phòng lúc chạy. Chuỗi rỗng = xoá lựa chọn, quay về ăn theo Backend URL.
 * Nối lại phòng ngay, không cần F5.
 */
export function setRoomBaseUrl(url) {
  const clean = String(url || "").trim();
  try {
    if (clean) localStorage.setItem(ROOM_BASE_KEY, JSON.stringify(clean));
    else localStorage.removeItem(ROOM_BASE_KEY);
  } catch {
    // localStorage bị chặn -> lựa chọn không sống qua F5, nhưng phiên này vẫn đúng
  }
  const next = resolveRoomBaseUrl();
  roomClient.rebase(next);
  return next;
}

// Nối phòng vào sự kiện đổi base URL của apiClient. Đăng ký ở đây (module scope)
// thay vì trong useRoom: roomClient là singleton, còn hook thì mount/unmount.
//
// CHỈ đi theo khi phòng đang ăn theo backend chính. Đã đặt Room URL riêng thì
// đổi Backend URL là việc của riêng phần search - đá phòng sang host mới lúc đó
// là kéo cả nhóm ra khỏi giỏ chung.
subscribeBaseUrl((url) => {
  if (hasOwnRoomBaseUrl()) return;
  roomClient.rebase(url);
});

export default roomClient;
