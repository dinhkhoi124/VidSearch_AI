// Kiểm thứ tự ưu tiên của Room URL - chạy: node src/api/roomBaseUrl.test.mjs
//
// Không import roomClient.js thật: nó kéo theo axios, import.meta.env của Vite
// và WebSocket của trình duyệt. Ở đây dựng lại ĐÚNG cây quyết định của
// resolveRoomBaseUrl()/hasOwnRoomBaseUrl() và khoá nó bằng test - cùng kiểu
// "bản sao có kiểm chứng" như basketReducer.js với room_store.py.
//
// Sửa thứ tự ưu tiên trong roomClient.js mà quên file này thì test vẫn xanh,
// nên khi đụng vào đó phải sửa cả hai.

let store = {};
const localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: (k) => { delete store[k]; },
};

const ROOM_BASE_KEY = "aic.roomBase";

function readJSON(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

// env = import.meta.env, apiBase = resolveBaseUrl() của apiClient
function resolveRoomBaseUrl(env, apiBase) {
  const stored = readJSON(ROOM_BASE_KEY, null);
  if (stored) return stored;
  return env.VITE_ROOM_BASE_URL || apiBase;
}

function hasOwnRoomBaseUrl(env) {
  return !!(readJSON(ROOM_BASE_KEY, null) || env.VITE_ROOM_BASE_URL);
}

function setRoomBaseUrl(url) {
  const clean = String(url || "").trim();
  if (clean) localStorage.setItem(ROOM_BASE_KEY, JSON.stringify(clean));
  else localStorage.removeItem(ROOM_BASE_KEY);
}

// --- chạy test ---------------------------------------------------------------
let failed = 0;
function check(name, actual, expected) {
  const ok = actual === expected;
  console.log(`  ${ok ? "ok " : "FAIL"}  ${name}`);
  if (!ok) {
    console.log(`        mong đợi: ${JSON.stringify(expected)}`);
    console.log(`        nhận được: ${JSON.stringify(actual)}`);
    failed++;
  }
}
function reset() { store = {}; }

const API = "http://localhost:8000";
const ROOM = "https://room.trycloudflare.com";
const ENV_ROOM = "https://env-room.trycloudflare.com";

console.log("\n- Thứ tự ưu tiên -");
reset();
check("trống -> rơi về Backend URL", resolveRoomBaseUrl({}, API), API);
check("trống -> KHÔNG coi là URL riêng", hasOwnRoomBaseUrl({}), false);

reset();
check(".env đứng trên Backend URL", resolveRoomBaseUrl({ VITE_ROOM_BASE_URL: ENV_ROOM }, API), ENV_ROOM);
check(".env -> tính là URL riêng", hasOwnRoomBaseUrl({ VITE_ROOM_BASE_URL: ENV_ROOM }), true);

reset();
setRoomBaseUrl(ROOM);
check("localStorage đứng trên .env", resolveRoomBaseUrl({ VITE_ROOM_BASE_URL: ENV_ROOM }, API), ROOM);
check("localStorage -> tính là URL riêng", hasOwnRoomBaseUrl({}), true);

console.log("\n- Xoá lựa chọn -");
reset();
setRoomBaseUrl(ROOM);
setRoomBaseUrl("");
check("lưu chuỗi rỗng -> quay lại ăn theo Backend URL", resolveRoomBaseUrl({}, API), API);
check("lưu chuỗi rỗng -> hết là URL riêng", hasOwnRoomBaseUrl({}), false);

reset();
setRoomBaseUrl("   ");
check("chỉ toàn khoảng trắng cũng là xoá", resolveRoomBaseUrl({}, API), API);

console.log("\n- Đổi Backend URL -");
// Đây là điểm mấu chốt của cả tính năng: 5 người mỗi người một backend search,
// chung một phòng. Đổi Backend URL KHÔNG được kéo phòng đi theo.
reset();
setRoomBaseUrl(ROOM);
check("phòng đứng yên khi Backend URL đổi", resolveRoomBaseUrl({}, "http://192.168.1.50:8000"), ROOM);
check("-> subscribeBaseUrl phải bỏ qua", hasOwnRoomBaseUrl({}), true);

reset();
check("chưa đặt Room URL thì phòng đi theo Backend URL", resolveRoomBaseUrl({}, "http://192.168.1.50:8000"), "http://192.168.1.50:8000");
check("-> subscribeBaseUrl phải rebase", hasOwnRoomBaseUrl({}), false);

console.log();
if (failed) {
  console.log(`THẤT BẠI: ${failed} kiểm tra`);
  process.exit(1);
}
console.log("TẤT CẢ ĐỀU PASS");
