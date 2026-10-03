// src/components/SettingsModal.jsx
// Cấu hình runtime: backend base URL.
//
// Trước đây ở đây còn endpoint/token "nộp live" kiểu DRES - đã gỡ: thể lệ BTC
// 2026 nộp bằng cách upload file .zip trực tiếp trên hệ thống thi (tài khoản BTC
// cấp cho đội), không có API chấm trực tiếp.
import { useCallback, useEffect, useRef, useState } from "react";
import { resolveBaseUrl, setApiBaseUrl, defaultBaseUrl } from "../api/apiClient";
import { hasOwnRoomBaseUrl, resolveRoomBaseUrl, setRoomBaseUrl } from "../api/roomClient";
import {
  getLlmConfig, getLlmStatus, setGeminiKey, setLlmConfig,
} from "../api/searchService";
import { setLlmStatus } from "../api/llmStatus";
import { SettingsIcon, CloseIcon } from "./Icons";

// Mốc ngưỡng gộp trùng, kèm mô tả cái mà mỗi mốc thực sự bắt được. Đo trên một
// pool 800 ứng viên thật (siglip512): 0.99 gộp 58 frame, 0.95 gộp 332, 0.90 gộp
// 537 — dốc nhất nằm trong khoảng 0.98–0.93.
const DEDUP_MARKS = [
  { v: 0.99, note: "gần như y hệt từng điểm ảnh" },
  { v: 0.975, note: "mặc định — bản phát lại / re-encode ở video khác" },
  { v: 0.96, note: "cùng một cảnh, lệch chút thời điểm" },
  { v: 0.93, note: "gộp cả frame khác nhau trong cùng shot" },
  { v: 0.90, note: "mạnh tay — bắt đầu nuốt cảnh khác nội dung" },
];

// 0.975 phải hiện đủ 3 chữ số — toFixed(2) làm tròn thành "0.98", tức là nhãn
// nói một ngưỡng khác với ngưỡng nút đó thực sự đặt.
const fmtThr = (v) => (Math.round(v * 1000) % 10 === 0 ? v.toFixed(2) : v.toFixed(3));

// Bốn chế độ của LLM_PROVIDER. Nhãn nói thẳng CÓ ĐƯỜNG LUI HAY KHÔNG, vì đó là
// khác biệt thực sự giữa chúng: hai chế độ "chỉ ..." mà provider đó chết giữa
// buổi thi thì agent câm hẳn, còn hai chế độ kia tự rơi sang bên còn lại.
const LLM_PROVIDER_MARKS = [
  { v: "auto", label: "auto", note: "Gemini chạy chính, OpenAI-compat đỡ khi Gemini hỏng" },
  { v: "openai_first", label: "openai_first", note: "OpenAI-compat chạy chính, Gemini đỡ khi nó hỏng" },
  { v: "gemini", label: "gemini", note: "CHỈ Gemini — không có đường lui" },
  { v: "openai", label: "openai", note: "CHỈ OpenAI-compat — không có đường lui" },
];

function SettingsModal({ isOpen, onClose, room, dedup }) {
  const [apiBase, setApiBase] = useState(resolveBaseUrl());
  // Trống = ăn theo Backend URL. Chỉ đổ sẵn giá trị khi người dùng thực sự đã
  // đặt URL riêng, để ô này nhìn là biết đang ở chế độ nào.
  const [roomBase, setRoomBase] = useState(() => (hasOwnRoomBaseUrl() ? resolveRoomBaseUrl() : ""));
  const [saved, setSaved] = useState(false);

  // --- Key Gemini ---
  const [geminiKey, setGeminiKeyValue] = useState("");
  const [llm, setLlm] = useState(null);        // snapshot /agent/llm_status
  const [llmMissing, setLlmMissing] = useState(false);  // backend bản cũ, chưa có endpoint
  const [keyBusy, setKeyBusy] = useState(false);
  const [keyMsg, setKeyMsg] = useState(null);  // {ok: boolean, text: string}

  // --- Provider + model OpenAI-compat (đổi nóng, không restart backend) ---
  // cfg = thứ backend ĐANG chạy; draft = thứ đang gõ trong form. Tách đôi để
  // biết field nào thực sự đổi mà chỉ gửi đúng field đó: gửi cả form thì mỗi
  // lần bấm Áp dụng lại ghi đè cả những ô người khác vừa đặt.
  const [cfg, setCfg] = useState(null);
  const [cfgMissing, setCfgMissing] = useState(false);   // backend bản cũ
  const [draft, setDraft] = useState(null);
  const [openaiKey, setOpenaiKey] = useState("");        // rỗng = giữ key cũ
  const [cfgBusy, setCfgBusy] = useState(false);
  const [cfgMsg, setCfgMsg] = useState(null);            // {ok, text}

  const draftFromConfig = (c) => ({
    provider: c.provider || "auto",
    openai_base_url: c.openai?.base_url || "",
    openai_model: c.openai?.model || "",
    openai_react_model: c.openai?.react_model || "",
    openai_qa_model: c.openai?.qa_model || "",
  });

  const refreshCfg = useCallback(async () => {
    try {
      const data = await getLlmConfig();
      setCfg(data);
      setDraft(draftFromConfig(data));
      setCfgMissing(false);
    } catch {
      setCfg(null);
      setDraft(null);
      setCfgMissing(true);
    }
  }, []);

  const applyCfg = async () => {
    if (!draft || !cfg || cfgBusy) return;
    // Chỉ những field ĐÃ ĐỔI. Field vắng mặt = backend giữ nguyên, nên bấm Áp
    // dụng khi chỉ sửa provider sẽ không đụng gì tới model/endpoint.
    const base = draftFromConfig(cfg);
    const patch = {};
    for (const k of Object.keys(base)) {
      if ((draft[k] || "").trim() !== base[k]) patch[k] = (draft[k] || "").trim();
    }
    if (openaiKey.trim()) patch.openai_api_key = openaiKey.trim();
    if (Object.keys(patch).length === 0) {
      setCfgMsg({ ok: true, text: "Không có gì thay đổi." });
      return;
    }
    setCfgBusy(true);
    setCfgMsg(null);
    try {
      const data = await setLlmConfig(patch);
      // Key ra khỏi ô ngay: backend hay chạy trên máy chiếu giữa phòng thi.
      setOpenaiKey("");
      setCfg(data.config);
      setDraft(draftFromConfig(data.config));
      setCfgMsg({ ok: true, text: data.message });
      refreshLlm();   // provider đổi -> banner quota phải nói về provider mới
    } catch (err) {
      setCfgMsg({
        ok: false,
        text: err.response?.data?.detail || err.message || "Không đổi được cấu hình.",
      });
    } finally {
      setCfgBusy(false);
    }
  };

  const refreshLlm = useCallback(async () => {
    try {
      const data = await getLlmStatus();
      setLlm(data);
      setLlmMissing(false);
      setLlmStatus(data); // đẩy luôn cho banner cảnh báo ngoài trang
    } catch {
      setLlm(null);
      setLlmMissing(true);
    }
  }, []);

  // Trạng thái key chỉ có nghĩa lúc hộp thoại đang mở; đóng vào là thôi hỏi.
  useEffect(() => {
    if (isOpen) { refreshLlm(); refreshCfg(); }
  }, [isOpen, refreshLlm, refreshCfg]);

  // --- Tên hiển thị trong phòng ---
  const memberName = room?.member?.name || "";
  const [nameDraft, setNameDraft] = useState(memberName);
  const [renamed, setRenamed] = useState(false);
  // Nạp lại mỗi lần mở, và khi tên đổi từ nơi khác (vừa join qua RoomJoinModal,
  // hoặc chính cú đổi tên vừa rồi) - ô nhập không được kẹt ở tên cũ.
  useEffect(() => {
    if (isOpen) { setNameDraft(memberName); setRenamed(false); }
  }, [isOpen, memberName]);

  // Bấm nền để đóng - nhưng chỉ khi cú bấm BẮT ĐẦU ở nền.
  //
  // Bôi đen nội dung một ô (Backend URL, key…) rồi nhả chuột ra ngoài hộp vẫn
  // sinh một sự kiện `click` có target là cái nền, nên đóng theo click trần là
  // mất trắng thứ đang gõ dở - đúng lúc đang sửa URL backend giữa buổi thi.
  // Nhớ điểm bắt đầu rồi mới quyết: xuống ở nền VÀ nhả ở nền mới là muốn đóng.
  // (Hook nên phải nằm trên chỗ return sớm ngay dưới.)
  const downOnBackdrop = useRef(false);

  if (!isOpen) return null;

  const applyGeminiKey = async () => {
    const key = geminiKey.trim();
    if (!key || keyBusy) return;
    setKeyBusy(true);
    setKeyMsg(null);
    try {
      const data = await setGeminiKey(key);
      // Xoá khỏi ô nhập ngay: không để key nằm phơi trên màn hình máy chiếu.
      setGeminiKeyValue("");
      setKeyMsg({ ok: true, text: data.message });
      await refreshLlm();
    } catch (err) {
      setKeyMsg({
        ok: false,
        text: err.response?.data?.detail || err.message || "Không đổi được key.",
      });
    } finally {
      setKeyBusy(false);
    }
  };

  // Đổi tên áp dụng NGAY, không chờ nút "Lưu" ở đáy: nút đó chỉ đặt lại base URL
  // (và làm đứt kết nối phòng). Gộp hai việc vào một nút thì đổi mỗi cái tên
  // cũng kéo theo một lần rebase backend.
  const applyRename = () => {
    const next = nameDraft.trim();
    if (!next || next === memberName) return;
    room.rename(next);
    setRenamed(true);
    setTimeout(() => setRenamed(false), 1500);
  };

  const handleBackdropDown = (e) => {
    downOnBackdrop.current = e.target === e.currentTarget;
  };
  const handleBackdropClick = (e) => {
    const close = downOnBackdrop.current && e.target === e.currentTarget;
    downOnBackdrop.current = false;
    if (close) onClose();
  };

  const handleSave = () => {
    // Thứ tự có ý nghĩa: đặt apiBase trước. Khi ô Room URL để trống, phòng ăn
    // theo apiBase, và setApiBaseUrl đã tự rebase phòng sang host mới.
    setApiBaseUrl(apiBase);
    setRoomBaseUrl(roomBase);
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  };

  const field = "w-full px-3 py-2 bg-white border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500";
  const label = "block text-sm font-semibold mb-1 text-slate-700";

  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-900/40 p-4"
      onPointerDown={handleBackdropDown}
      onClick={handleBackdropClick}
    >
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg text-slate-800 border border-slate-200 max-h-[88vh] flex flex-col">
        <div className="shrink-0 bg-slate-50 border-b border-slate-200 p-3 rounded-t-xl flex justify-between items-center">
          <span className="inline-flex items-center gap-2 font-semibold"><SettingsIcon className="w-5 h-5 text-slate-500" /> Cài đặt</span>
          <button onClick={onClose} className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100"><CloseIcon className="w-4 h-4" /></button>
        </div>
        {/* min-h-0: không có nó thì flex item từ chối co lại dưới nội dung và
            overflow-y-auto vô tác dụng - hộp thoại lại cao hơn màn hình. */}
        <div className="p-4 space-y-4 overflow-y-auto min-h-0">
          <div>
            <label className={label}>Backend URL</label>
            <input className={field} value={apiBase} onChange={(e) => setApiBase(e.target.value)} placeholder={defaultBaseUrl()} />
            <p className="text-xs text-slate-400 mt-1">Áp dụng ngay cho mọi request. Để trống = tự suy từ host đang mở ({defaultBaseUrl()}).</p>
          </div>
          <div>
            <label className={label}>Room URL <span className="font-normal text-slate-400">(giỏ đáp án chung)</span></label>
            <input className={field} value={roomBase} onChange={(e) => setRoomBase(e.target.value)} placeholder={apiBase || defaultBaseUrl()} />
            <p className="text-xs text-slate-400 mt-1">
              Để trống = giỏ nằm trên chính Backend URL ở trên. Điền vào khi cả nhóm mỗi
              người chạy backend riêng nhưng muốn chung một giỏ - mọi người dán CÙNG một URL.
            </p>
          </div>
          {/* Key Gemini — đổi NÓNG. Key free tier cạn ~20-1000 request/ngày tuỳ
              model, cạn giữa buổi thi thì restart backend mất ~10 phút nạp lại
              model, quá đắt. Dán key khác vào đây là chạy tiếp ngay. */}
          <div className="border-t border-slate-200 pt-4">
            <label className={label}>Gemini API key</label>
            <div className="flex gap-2">
              <input
                className={field}
                type="password"
                autoComplete="off"
                spellCheck={false}
                value={geminiKey}
                onChange={(e) => setGeminiKeyValue(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") applyGeminiKey(); }}
                placeholder="AIza…"
                disabled={keyBusy || llm?.configured?.can_set_key === false}
              />
              <button
                onClick={applyGeminiKey}
                disabled={keyBusy || !geminiKey.trim() || llm?.configured?.can_set_key === false}
                className="shrink-0 px-3 py-2 rounded-lg text-sm font-semibold bg-slate-800 text-white hover:bg-slate-900 disabled:bg-slate-200 disabled:text-slate-400 transition-colors"
              >
                {keyBusy ? "Đang thử…" : "Áp dụng"}
              </button>
            </div>

            {keyMsg && (
              <p className={`text-xs mt-1.5 ${keyMsg.ok ? "text-emerald-600" : "text-rose-600"}`}>
                {keyMsg.text}
              </p>
            )}

            {llmMissing ? (
              <p className="text-xs text-amber-600 mt-1">
                Backend chưa có endpoint đổi key — bản cũ, cập nhật code rồi khởi động lại.
              </p>
            ) : llm?.configured?.can_set_key === false ? (
              <p className="text-xs text-amber-600 mt-1">
                Backend đang tắt đổi key runtime (ALLOW_RUNTIME_LLM_KEY=false).
              </p>
            ) : (
              <p className="text-xs text-slate-400 mt-1">
                {llm?.configured?.gemini
                  ? <>Đang dùng key <b className="font-mono">{llm.configured.gemini_key_hint}</b> · model <b className="font-mono">{llm.configured.gemini_model}</b>. </>
                  : <>Backend đang KHÔNG có key Gemini nào. </>}
                Backend thử key trước khi nhận. Key chỉ nằm trong RAM — restart là quay về .env,
                và ai vào được backend cũng ghi đè được key.
              </p>
            )}

            {llm?.exhausted && (
              <p className="text-xs text-amber-700 mt-1">
                Key {llm.provider} hiện tại đang hết lượt truy cập
                {llm.scope === "day" ? " (hết hạn mức theo ngày)" : ""} — dán key khác vào đây để chạy tiếp.
              </p>
            )}
          </div>

          {/* Provider + model OpenAI-compat — đổi NÓNG, cùng lý do với ô key ở
              trên. Thứ hỏng giữa buổi thi hay là phía LLM: OpenRouter hết
              credit, tunnel Ollama trên Colab đứt, model text-thuần chết ở bước
              QA vì bước đó gửi ẢNH. Restart backend để sửa mất ~10 phút nạp lại
              model visual, nên mọi thứ ở đây áp dụng ngay trong RAM. */}
          <details className="border-t border-slate-200 pt-4 group">
            {/* [&::-webkit-details-marker]:hidden: list-none KHÔNG giấu được
                tam giác mặc định trên WebKit, nó cần selector riêng. */}
            <summary className="cursor-pointer list-none [&::-webkit-details-marker]:hidden flex items-center justify-between">
              {/* Không tái dùng biến `label` ở đây: nó đã mang mb-1, mà ghi đè
                  bằng mb-0 trong cùng class attr thì thứ tự CSS quyết định chứ
                  không phải thứ tự chữ -> có hôm thắng, có hôm không. */}
              <span className="text-sm font-semibold text-slate-700">Provider LLM &amp; model</span>
              <span className="text-xs text-slate-400 font-mono">
                {cfg ? `${cfg.provider} · ${cfg.openai?.model || "—"}` : "…"}
                <span className="ml-1 inline-block group-open:rotate-90 transition-transform">›</span>
              </span>
            </summary>
            <div className="pt-2">
            {cfgMissing ? (
              <p className="text-xs text-amber-600">
                Backend chưa có endpoint đổi cấu hình LLM — bản cũ, cập nhật code rồi khởi động lại.
              </p>
            ) : !draft ? (
              <p className="text-xs text-slate-400">Đang đọc cấu hình…</p>
            ) : (
              <>
                <div className="flex gap-1.5 flex-wrap">
                  {LLM_PROVIDER_MARKS.map((m) => (
                    <button
                      key={m.v}
                      onClick={() => setDraft({ ...draft, provider: m.v })}
                      title={m.note}
                      disabled={cfg?.can_edit === false}
                      className={`px-2.5 py-1 rounded text-xs font-semibold font-mono transition-colors disabled:opacity-40 ${
                        draft.provider === m.v
                          ? "bg-indigo-600 text-white"
                          : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                      }`}
                    >
                      {m.label}
                    </button>
                  ))}
                </div>
                <p className="text-xs text-slate-400 mt-1.5">
                  {LLM_PROVIDER_MARKS.find((m) => m.v === draft.provider)?.note}
                  {cfg?.provider !== draft.provider && (
                    <b className="text-indigo-600"> · chưa áp dụng, bấm nút bên dưới</b>
                  )}
                </p>

                <div className="mt-3 space-y-2">
                  <div>
                    <label className="block text-xs font-semibold text-slate-600 mb-1">
                      Model OpenAI-compat
                    </label>
                    <input
                      className={field}
                      value={draft.openai_model}
                      onChange={(e) => setDraft({ ...draft, openai_model: e.target.value })}
                      onKeyDown={(e) => { if (e.key === "Enter") applyCfg(); }}
                      placeholder="vd google/gemini-3.7-flash"
                      spellCheck={false}
                      disabled={cfg?.can_edit === false}
                    />
                  </div>
                  {/* Hai ô riêng theo nhiệm vụ: QA gửi ẢNH nên PHẢI là model
                      vision, ReAct thì cần suy luận tốt. Rỗng = dùng lại ô trên,
                      mà nhìn ô rỗng không ai đoán ra điều đó -> in ra model
                      THỰC SỰ đang chạy ngay dưới. */}
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="block text-xs font-semibold text-slate-600 mb-1">
                        Model ReAct <span className="font-normal text-slate-400">(rỗng = như trên)</span>
                      </label>
                      <input
                        className={field}
                        value={draft.openai_react_model}
                        onChange={(e) => setDraft({ ...draft, openai_react_model: e.target.value })}
                        onKeyDown={(e) => { if (e.key === "Enter") applyCfg(); }}
                        placeholder={draft.openai_model || "—"}
                        spellCheck={false}
                        disabled={cfg?.can_edit === false}
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-semibold text-slate-600 mb-1">
                        Model QA <span className="font-normal text-slate-400">(phải nhận ảnh)</span>
                      </label>
                      <input
                        className={field}
                        value={draft.openai_qa_model}
                        onChange={(e) => setDraft({ ...draft, openai_qa_model: e.target.value })}
                        onKeyDown={(e) => { if (e.key === "Enter") applyCfg(); }}
                        placeholder={draft.openai_model || "—"}
                        spellCheck={false}
                        disabled={cfg?.can_edit === false}
                      />
                    </div>
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-600 mb-1">
                      Base URL <span className="font-normal text-slate-400">(đổi khi tunnel Colab đứt)</span>
                    </label>
                    <input
                      className={field}
                      value={draft.openai_base_url}
                      onChange={(e) => setDraft({ ...draft, openai_base_url: e.target.value })}
                      onKeyDown={(e) => { if (e.key === "Enter") applyCfg(); }}
                      placeholder="https://openrouter.ai/api/v1"
                      spellCheck={false}
                      disabled={cfg?.can_edit === false}
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-600 mb-1">
                      API key <span className="font-normal text-slate-400">(rỗng = giữ key đang dùng)</span>
                    </label>
                    <input
                      className={field}
                      type="password"
                      autoComplete="off"
                      spellCheck={false}
                      value={openaiKey}
                      onChange={(e) => setOpenaiKey(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter") applyCfg(); }}
                      placeholder={cfg?.openai?.configured ? `đang dùng ${cfg.openai.key_hint}` : "sk-…"}
                      disabled={cfg?.can_edit === false}
                    />
                  </div>
                </div>

                <button
                  onClick={applyCfg}
                  disabled={cfgBusy || cfg?.can_edit === false}
                  className="mt-2.5 px-3 py-1.5 rounded-lg text-sm font-semibold bg-slate-800 text-white hover:bg-slate-900 disabled:bg-slate-200 disabled:text-slate-400 transition-colors"
                >
                  {cfgBusy ? "Đang áp dụng…" : "Áp dụng cấu hình LLM"}
                </button>

                {cfgMsg && (
                  <p className={`text-xs mt-1.5 ${cfgMsg.ok ? "text-emerald-600" : "text-rose-600"}`}>
                    {cfgMsg.text}
                  </p>
                )}

                {cfg?.can_edit === false ? (
                  <p className="text-xs text-amber-600 mt-1">
                    Backend đang tắt đổi cấu hình LLM runtime (ALLOW_RUNTIME_LLM_KEY=false).
                  </p>
                ) : (
                  <p className="text-xs text-slate-400 mt-1">
                    Đang chạy: <b className="font-mono">{cfg?.provider}</b> · endpoint{" "}
                    <b className="font-mono">{cfg?.openai?.host}</b> key{" "}
                    <b className="font-mono">{cfg?.openai?.key_hint}</b> · ReAct{" "}
                    <b className="font-mono">{cfg?.openai?.effective_react || "(chưa đặt)"}</b> · QA{" "}
                    <b className="font-mono">{cfg?.openai?.effective_qa || "(chưa đặt)"}</b>.
                    Chỉ nằm trong RAM — restart backend là quay về .env.
                  </p>
                )}
              </>
            )}
            </div>
          </details>

          {/* Gộp frame trùng thị giác. Ngưỡng quyết định cách chia cụm Ở BACKEND
              nên đổi xong phải tìm lại — có nút ngay dưới để hiệu chỉnh nhanh. */}
          {dedup && (
            <div className="border-t border-slate-200 pt-4">
              <div className="flex items-center justify-between">
                <label className={label}>Gộp frame trùng</label>
                <label className="flex items-center gap-1.5 cursor-pointer text-sm">
                  <input
                    type="checkbox"
                    className="accent-blue-600"
                    checked={dedup.enabled}
                    onChange={(e) => dedup.setEnabled(e.target.checked)}
                  />
                  <span className="text-slate-600">{dedup.enabled ? "Bật" : "Tắt"}</span>
                </label>
              </div>
              <div className={`mt-2 ${dedup.enabled ? "" : "opacity-40 pointer-events-none"}`}>
                <div className="flex items-center gap-3">
                  <input
                    type="range"
                    min="0.85"
                    max="1"
                    step="0.005"
                    value={dedup.threshold}
                    onChange={(e) => dedup.setThreshold(Number(e.target.value))}
                    className="flex-1 accent-indigo-600"
                  />
                  <input
                    type="number"
                    min="0.85"
                    max="1"
                    step="0.005"
                    value={dedup.threshold}
                    onChange={(e) => dedup.setThreshold(Number(e.target.value))}
                    className="w-20 px-2 py-1 bg-white border border-slate-300 rounded text-sm tabular-nums"
                  />
                </div>
                <div className="flex gap-1.5 mt-2 flex-wrap">
                  {DEDUP_MARKS.map((m) => (
                    <button
                      key={m.v}
                      onClick={() => dedup.setThreshold(m.v)}
                      title={m.note}
                      className={`px-2 py-1 rounded text-xs font-semibold tabular-nums transition-colors ${
                        Math.abs(dedup.threshold - m.v) < 0.0025
                          ? "bg-indigo-600 text-white"
                          : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                      }`}
                    >
                      {fmtThr(m.v)}
                    </button>
                  ))}
                </div>
                <p className="text-xs text-slate-400 mt-1.5">
                  {DEDUP_MARKS.reduce((best, m) =>
                    Math.abs(dedup.threshold - m.v) < Math.abs(dedup.threshold - best.v) ? m : best
                  ).note}
                  . Cosine giữa hai vector SigLIP; càng thấp càng gộp mạnh. Bản trùng
                  không bị xoá — bấm badge ×N trên ô để xem cả cụm.
                </p>
                {dedup.onRerun && (
                  <button
                    onClick={() => { dedup.onRerun(); onClose(); }}
                    className="mt-2 px-3 py-1.5 rounded-lg text-sm font-semibold bg-slate-800 text-white hover:bg-slate-900 transition-colors"
                  >
                    Tìm lại với ngưỡng này
                  </button>
                )}
              </div>
            </div>
          )}

          {room && (
            <div className="border-t border-slate-200 pt-4">
              <label className={label}>Phòng nhóm</label>

              {/* Đổi tên hiển thị. Hiện cả khi đang làm một mình, miễn là đã
                  từng đặt tên - để sửa sẵn trước khi vào phòng. Chưa có tên thì
                  đường đặt tên là RoomJoinModal, không phải ở đây. */}
              {room.member && (
                <div className="mb-2">
                  <div className="flex items-center gap-2">
                    <input
                      className={field}
                      value={nameDraft}
                      onChange={(e) => setNameDraft(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); applyRename(); } }}
                      placeholder="Tên hiển thị"
                      maxLength={40}
                    />
                    <button
                      onClick={applyRename}
                      disabled={!nameDraft.trim() || nameDraft.trim() === memberName}
                      className="shrink-0 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white transition-colors hover:bg-blue-700 disabled:bg-slate-200 disabled:text-slate-400"
                    >
                      Đổi tên
                    </button>
                  </div>
                  <p className="mt-1 text-xs text-slate-400">
                    {renamed ? (
                      <span className="font-semibold text-emerald-600">Đã đổi tên · đang nối lại phòng…</span>
                    ) : (
                      <>Vẫn là cùng một người với server (danh tính theo ID, không theo tên) - đổi tên không tạo thêm thành viên. Frame đã thêm trước đó vẫn mang nhãn tên cũ.</>
                    )}
                  </p>
                </div>
              )}

              {room.active ? (
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm text-slate-600">
                    Đang ở phòng với tên <b>{room.member?.name}</b>
                    {room.status.connected
                      ? <span className="text-emerald-600"> · đã kết nối</span>
                      : <span className="text-amber-600"> · mất kết nối, {room.status.pending} thao tác chờ</span>}
                  </p>
                  <button
                    onClick={room.leave}
                    className="shrink-0 text-sm text-rose-600 hover:text-rose-700 font-semibold"
                  >
                    Rời phòng
                  </button>
                </div>
              ) : (
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm text-slate-600">
                    Đang làm một mình - giỏ đáp án chỉ nằm trên máy này.
                  </p>
                  <button
                    onClick={room.enable}
                    className="shrink-0 text-sm text-blue-600 hover:text-blue-700 font-semibold"
                  >
                    Vào phòng
                  </button>
                </div>
              )}
              <p className="text-xs text-slate-400 mt-1">
                Phòng dùng chung Backend URL ở trên. Rời phòng KHÔNG xoá giỏ đang có trên máy.
              </p>
            </div>
          )}
        </div>
        <div className="shrink-0 p-4 border-t border-slate-200 flex justify-end items-center gap-3">
          {saved && <span className="text-emerald-600 text-sm font-medium">Đã lưu</span>}
          <button onClick={handleSave} className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg font-semibold text-sm transition-colors">Lưu</button>
        </div>
      </div>
    </div>
  );
}

export default SettingsModal;
