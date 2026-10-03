// src/hooks/useSubmissionLog.js
// NHẬT KÝ LƯỢT NỘP. BTC cho tối đa 3 lượt mỗi gói truy vấn và CHẤM LƯỢT CUỐI
// CÙNG - nộp sai định dạng vẫn trừ một lượt. Nên chỗ này phải trả lời được hai
// câu: "gói này còn mấy lượt?" và "bản cuối mình nộp có gì trong đó?".
//
// Mỗi lần bấm tải zip là ghi một mục, kèm nguyên nội dung các file CSV (vài
// chục KB) để tải lại đúng bản đã nộp mà không phải dựng lại giỏ.
//
// PHÒNG THI NHÓM: đếm lượt trên MỘT máy là sai - 5 người mỗi người bấm tải một
// bản thì máy nào cũng thấy "Lượt 1/3" trong khi cả nhóm đã dùng hết. Nên khi có
// `room`, mục vừa ghi được đẩy lên phòng và mục của đồng đội được trộn vào để
// đếm. Chỉ đồng bộ METADATA (thời điểm, tên gói/zip, danh sách file + số dòng):
// đẩy cả nội dung CSV lên sẽ phình room state và file snapshot, mà bản zip để
// tải lại thì chỉ máy tạo ra nó mới cần.
import { useCallback, useEffect, useMemo, useState } from "react";

const KEY = "aic.submitlog";
export const MAX_ATTEMPTS = 3;

const packageKey = (name) => String(name || "").trim() || "(chưa đặt tên gói)";

function load() {
  try {
    const raw = localStorage.getItem(KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

export function useSubmissionLog(room) {
  const [entries, setEntries] = useState(load);

  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(entries));
    } catch {
      // localStorage đầy -> bỏ qua, không được làm vỡ luồng nộp
    }
  }, [entries]);

  // Trộn mục của máy này (có nội dung CSV) với mục phòng phát về (chỉ metadata),
  // khử trùng theo id - chính mục mình vừa gửi sẽ quay lại qua broadcast.
  const roomEntries = room?.submitLog;
  const merged = useMemo(() => {
    if (!Array.isArray(roomEntries) || roomEntries.length === 0) return entries;
    const mine = new Set(entries.map((e) => e.id));
    // `remote` = của máy khác: không có nội dung CSV nên không tải lại / xoá được.
    const extra = roomEntries
      .filter((e) => e && e.id && !mine.has(e.id))
      .map((e) => ({ ...e, files: e.files || [], remote: true }));
    return [...entries, ...extra].sort((a, b) => String(b.at).localeCompare(String(a.at)));
  }, [entries, roomEntries]);

  /**
   * @param {{packageName:string, zipName:string, files:Array<{filename,content}>}} info
   */
  const record = useCallback((info) => {
    const files = (info?.files || []).map((f) => ({ filename: f.filename, content: f.content }));
    const entry = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      at: new Date().toISOString(),
      packageName: packageKey(info?.packageName),
      zipName: info?.zipName || "submission.zip",
      files,
    };
    setEntries((prev) => [entry, ...prev]);
    room?.sendSubmitLog?.({
      id: entry.id,
      at: entry.at,
      package_name: entry.packageName,
      zip_name: entry.zipName,
      files: files.map((f) => ({
        filename: f.filename,
        rows: f.content ? f.content.split("\n").length : 0,
      })),
    });
    return entry;
  }, [room]);

  // Chỉ xoá được mục của máy này; mục phòng phát về là việc đã rồi của đồng đội.
  const remove = useCallback((id) => {
    setEntries((prev) => prev.filter((e) => e.id !== id));
  }, []);

  // Xoá cả bản local lẫn bản của phòng: chỉ xoá local thì mục của 4 máy kia vẫn
  // được trộn ngược vào ở `merged` và bộ đếm lượt không bao giờ về 0.
  const clearAll = useCallback(() => {
    setEntries([]);
    room?.clearSubmitLog?.();
  }, [room]);

  // Số lượt đã dùng, nhóm theo tên gói.
  const countFor = useCallback(
    (packageName) => {
      const name = packageKey(packageName);
      return merged.filter((e) => e.packageName === name).length;
    },
    [merged]
  );

  const entriesFor = useCallback(
    (packageName) => {
      const name = packageKey(packageName);
      return merged.filter((e) => e.packageName === name);
    },
    [merged]
  );

  const packages = useMemo(
    () => Array.from(new Set(merged.map((e) => e.packageName))),
    [merged]
  );

  return { entries: merged, record, remove, clearAll, countFor, entriesFor, packages };
}
