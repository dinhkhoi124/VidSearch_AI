// src/utils/submissionFormat.test.mjs
// Đối chiếu ĐÚNG TỪNG VÍ DỤ trong hướng dẫn nộp bài của BTC AIC 2026.
// Chạy: node src/utils/submissionFormat.test.mjs   (không cần dựng UI)
import assert from "node:assert/strict";
import {
  toCSV, chunkTrake, suggestFilename, sanitizeZipName, defaultQueryId, isAutoQueryId,
  buildExports, buildSubmissionZip, taskFromQueryId, charLen, parseCsvLine,
} from "./submissionFormat.js";
import { validateSubmission, hasErrors } from "./submissionValidate.js";
import { parseQueryFilename, guessNumEvents } from "./queryPackage.js";
import { parseFrameNumber, frameIndex } from "./frameIndex.js";
import { applyOp, normalize, toEntry } from "../hooks/basketReducer.js";

let pass = 0;
const test = (name, fn) => {
  try {
    fn();
    pass += 1;
    console.log(`  ok  ${name}`);
  } catch (e) {
    console.error(`FAIL  ${name}\n      ${e.message}`);
    process.exitCode = 1;
  }
};

const f = (video, idx, extra = {}) => ({
  id: `${video}_${idx}`, video_name: video, frame_idx: idx, answer: "", ...extra,
});

console.log("\n- KIS -");
test("đúng ví dụ KIS của BTC", () => {
  const csv = toCSV([f("L00_V000", 1234), f("L00_V055", 5555), f("L01_V028", 25300)], "kis");
  assert.equal(csv, "L00_V000,1234\nL00_V055,5555\nL01_V028,25300");
});
test("không có dòng header", () => {
  assert.ok(!toCSV([f("L00_V000", 1)], "kis").startsWith("video"));
});
test("cắt đúng maxRows", () => {
  const many = Array.from({ length: 150 }, (_, i) => f("L00_V000", i));
  assert.equal(toCSV(many, "kis").split("\n").length, 100, "phải kẹp ở trần 100 của BTC");
  assert.equal(toCSV(many, "kis", { maxRows: 10 }).split("\n").length, 10);
});

console.log("\n- Q&A -");
test("đúng ví dụ Q&A của BTC", () => {
  const csv = toCSV(
    [f("L01_V028", 3450, { answer: "5" }), f("L02_V011", 1200, { answer: "Năm người" })],
    "qa"
  );
  assert.equal(csv, "L01_V028,3450,5\nL02_V011,1200,Năm người");
});
test("answer có dấu phẩy -> bọc ngoặc kép", () => {
  const csv = toCSV([f("L03_V005", 2800, { answer: "Màu đỏ, rất đẹp" })], "qa");
  assert.equal(csv, 'L03_V005,2800,"Màu đỏ, rất đẹp"');
});
test("answer có ngoặc kép -> nhân đôi ngoặc kép", () => {
  const csv = toCSV([f("L04_V012", 4100, { answer: 'Anh ấy nói "Tuyệt vời"' })], "qa");
  assert.equal(csv, 'L04_V012,4100,"Anh ấy nói ""Tuyệt vời"""');
});
test("answer xuống dòng -> thay bằng dấu cách, KHÔNG bọc ngoặc kép", () => {
  // Bọc ngoặc kép là đúng RFC nhưng khi đó một dòng CSV trải trên hai dòng vật
  // lý; chương trình chấm đọc từng dòng sẽ thấy hai bản ghi rách. Ký tự xuống
  // dòng trong đáp án luôn là do dán nhầm, nên thay bằng dấu cách an toàn hơn -
  // và validateSubmission báo cảnh báo để người dùng biết nội dung đã đổi.
  const csv = toCSV([f("L01_V028", 3450, { answer: "Dòng 1\nDòng 2" })], "qa");
  assert.equal(csv, "L01_V028,3450,Dòng 1 Dòng 2");
});
test("khoảng trắng đầu/cuối answer bị cắt khi xuất", () => {
  // BTC "giữ nguyên, không tự động trim" và so khớp chuỗi -> " Năm người " là
  // một đáp án KHÁC. Phải cắt tại chỗ sinh file.
  assert.equal(
    toCSV([f("L02_V011", 1200, { answer: "  Năm người  " })], "qa"),
    "L02_V011,1200,Năm người"
  );
  // Khoảng trắng BÊN TRONG là một phần của đáp án, không được đụng.
  assert.equal(
    toCSV([f("L02_V011", 1200, { answer: "Năm  người" })], "qa"),
    "L02_V011,1200,Năm  người"
  );
});

console.log("\n- TRAKE -");
test("đúng ví dụ TRAKE của BTC (4 events, CÙNG video 2 dòng)", () => {
  // Đây là ca mà cách gộp-theo-video cũ làm sai: L10_V001 phải ra HAI dòng.
  const items = [
    f("L10_V001", 1200), f("L10_V001", 1850), f("L10_V001", 2100), f("L10_V001", 2450),
    f("L10_V001", 1180), f("L10_V001", 1820), f("L10_V001", 2080), f("L10_V001", 2420),
    f("L11_V003", 5100), f("L11_V003", 5700), f("L11_V003", 6200), f("L11_V003", 6800),
  ];
  const csv = toCSV(items, "trake", { numEvents: 4 });
  assert.equal(
    csv,
    "L10_V001,1200,1850,2100,2450\n" +
    "L10_V001,1180,1820,2080,2420\n" +
    "L11_V003,5100,5700,6200,6800"
  );
});
test("mỗi dòng có đúng N+1 trường", () => {
  const items = Array.from({ length: 9 }, (_, i) => f("L10_V001", 100 + i));
  for (const line of toCSV(items, "trake", { numEvents: 3 }).split("\n")) {
    assert.equal(line.split(",").length, 4, `dòng "${line}" phải có 1 video + 3 frame`);
  }
});
test("chunkTrake giữ nguyên khối thiếu frame để validate bắt lỗi", () => {
  const g = chunkTrake([f("A", 1), f("A", 2), f("A", 3), f("A", 4), f("A", 5)], 3);
  assert.equal(g.length, 2);
  assert.equal(g[1].length, 2, "khối cuối thiếu -> không được âm thầm vứt");
});
test("TRAKE chưa khai số event -> toCSV NÉM LỖI, không âm thầm cắt n=1", () => {
  // Đường "vẫn tải xuống dù còn lỗi" từng đi qua đây và sinh ra file mà mỗi
  // frame là một dòng - vẫn là CSV hợp lệ nên không gì bắt được.
  const items = [f("A", 10), f("A", 20), f("A", 30)];
  assert.throws(() => toCSV(items, "trake", {}), /chưa khai số event/i);
  assert.throws(() => toCSV(items, "trake", { numEvents: 0 }), /chưa khai số event/i);
});
test("maxRows cắt theo SỐ ỨNG VIÊN, không phải số frame", () => {
  const items = Array.from({ length: 20 }, (_, i) => f("A", i));
  assert.equal(toCSV(items, "trake", { numEvents: 4, maxRows: 3 }).split("\n").length, 3);
});
test("toCSV bỏ mục thiếu frame_idx rồi mới cắt khối", () => {
  const items = [
    f("A", 10), f("A", 20), f("A", 30),
    f("A", 40), f("A", null), f("A", 60), // mục hỏng nằm GIỮA chuỗi
    f("A", 70), f("A", 80), f("A", 90),
  ];
  assert.equal(toCSV(items, "trake", { numEvents: 3 }), "A,10,20,30\nA,40,60,70\nA,80,90");
});

console.log("\n- Tên file & zip -");
test("tên file khớp tên truy vấn BTC", () => {
  assert.equal(suggestFilename("query-1-kis"), "query-1-kis.csv");
  assert.equal(suggestFilename("query-4-trake"), "query-4-trake.csv");
});
test("queryId mặc định mang hậu tố task", () => {
  assert.equal(defaultQueryId(3, "qa"), "query-3-qa");
  assert.ok(isAutoQueryId("query-3-qa"));
  assert.ok(!isAutoQueryId("cau3_cua_toi"), "người dùng gõ tay -> không tự ghi đè");
});
test("tên zip chỉ còn chữ và số theo khuyến cáo BTC", () => {
  assert.equal(sanitizeZipName("team ABC / round 1"), "team_ABC_round_1.zip");
  assert.equal(sanitizeZipName("x.zip"), "x.zip");
  assert.equal(sanitizeZipName(""), "submission.zip");
});
test("buildExports: câu hỏng không làm hỏng cả gói, nhưng phải báo", () => {
  const files = buildExports([
    { qid: 1, taskType: "kis", queryId: "query-1-kis", maxRows: 100, items: [f("L01_V001", 10)] },
    // TRAKE thiếu numEvents -> xuất được câu 1, câu 2 kèm error.
    { qid: 2, taskType: "trake", queryId: "query-2-trake", maxRows: 100, items: [f("A", 1)] },
    // Có đáp án nhưng không mục nào xuất được -> file rỗng, phải bị đánh dấu.
    { qid: 3, taskType: "kis", queryId: "query-3-kis", maxRows: 100, items: [f("L03_V001", null)] },
  ]);
  assert.equal(files.length, 3);
  assert.equal(files[0].error, null);
  assert.equal(files[0].content, "L01_V001,10");
  assert.match(files[1].error, /số event/i);
  assert.match(files[2].error, /không mục nào/i);
});
test("taskFromQueryId đọc đúng hậu tố của tên truy vấn", () => {
  assert.equal(taskFromQueryId("query-3-qa"), "qa");
  assert.equal(taskFromQueryId("query-10-TRAKE"), "trake");
  assert.equal(taskFromQueryId("cau3_cua_toi"), null);
});
test("charLen đếm theo code point", () => {
  assert.equal(charLen("Năm người"), 9);
  assert.equal(charLen("👍"), 1, "emoji chỉ tính 1 ký tự, không phải 2 đơn vị UTF-16");
});

console.log("\n- Kiểm tra tiền-nộp -");
const q = (over) => ({ qid: 1, taskType: "kis", queryId: "query-1-kis", maxRows: 100, items: [], ...over });

test("giỏ hợp lệ -> không lỗi", () => {
  const issues = validateSubmission([q({ items: [f("L01_V001", 10), f("L01_V002", 20)] })]);
  assert.ok(!hasErrors(issues), JSON.stringify(issues));
});
test("Q&A thiếu câu trả lời -> lỗi", () => {
  const issues = validateSubmission([
    q({ taskType: "qa", queryId: "query-1-qa", items: [f("L01_V001", 10)] }),
  ]);
  assert.ok(hasErrors(issues));
  assert.ok(issues.some((i) => /chưa có câu trả lời/.test(i.msg)));
});
test("Q&A answer > 100 ký tự -> lỗi", () => {
  const issues = validateSubmission([
    q({ taskType: "qa", queryId: "query-1-qa", items: [f("L01_V001", 10, { answer: "x".repeat(101) })] }),
  ]);
  assert.ok(issues.some((i) => i.level === "error" && /vượt 100 ký tự/.test(i.msg)));
});
test("TRAKE chưa khai số event -> lỗi", () => {
  const issues = validateSubmission([
    q({ taskType: "trake", queryId: "query-1-trake", items: [f("A", 1)] }),
  ]);
  assert.ok(issues.some((i) => /Chưa khai số event/.test(i.msg)));
});
test("TRAKE khối thiếu frame -> lỗi", () => {
  const issues = validateSubmission([
    q({ taskType: "trake", queryId: "query-1-trake", numEvents: 4,
        items: [f("A", 1), f("A", 2), f("A", 3)] }),
  ]);
  assert.ok(issues.some((i) => /mới có 3\/4 frame/.test(i.msg)));
});
test("TRAKE lẫn video / sai thứ tự thời gian -> lỗi", () => {
  const mixed = validateSubmission([
    q({ taskType: "trake", queryId: "query-1-trake", numEvents: 2, items: [f("A", 1), f("B", 2)] }),
  ]);
  assert.ok(mixed.some((i) => /lẫn 2 video/.test(i.msg)));

  const unordered = validateSubmission([
    q({ taskType: "trake", queryId: "query-1-trake", numEvents: 2, items: [f("A", 9), f("A", 2)] }),
  ]);
  assert.ok(unordered.some((i) => /không tăng dần/.test(i.msg)));
});
test("tên video còn đuôi .mp4 -> lỗi", () => {
  const issues = validateSubmission([q({ items: [f("L01_V028.mp4", 10)] })]);
  assert.ok(issues.some((i) => i.level === "error" && /\.mp4/.test(i.msg)));
});
test("hai câu trùng tên file -> lỗi", () => {
  const issues = validateSubmission([
    q({ qid: 1, items: [f("A", 1)] }),
    q({ qid: 2, items: [f("B", 2)] }), // cùng queryId "query-1-kis"
  ]);
  assert.ok(issues.some((i) => /cùng ghi ra/.test(i.msg)));
});
test("trùng (video, frame) trong cùng câu -> cảnh báo, không chặn", () => {
  const issues = validateSubmission([
    q({ items: [f("A", 1), { ...f("A", 1), id: "khac-id" }] }),
  ]);
  assert.ok(!hasErrors(issues));
  assert.ok(issues.some((i) => i.level === "warn" && /trùng/.test(i.msg)));
});
test("frame_idx null -> lỗi (vì bị lọc âm thầm khỏi CSV)", () => {
  const issues = validateSubmission([q({ items: [f("A", null)] })]);
  assert.ok(issues.some((i) => /không đọc được frame_idx/.test(i.msg)));
});
test("TRAKE: khối mà validate báo phải TRÙNG khối trong file CSV", () => {
  // Regression: toCSV lọc mục thiếu frame_idx TRƯỚC khi cắt, còn validate cắt
  // trên danh sách chưa lọc -> số hiệu "Đáp án #k" không chỉ đúng dòng nào
  // trong file, và mọi ứng viên phía sau lệch đi một frame. Đường này có thật
  // vì UI có nút "Vẫn tải xuống dù còn lỗi".
  const items = [
    f("A", 10), f("A", 20), f("A", 30),
    f("A", 40), f("A", null), f("A", 60),
    f("A", 70), f("A", 80), f("A", 90),
  ];
  const rows = toCSV(items, "trake", { numEvents: 3 }).split("\n");
  assert.equal(rows.length, 3);

  const issues = validateSubmission([
    q({ taskType: "trake", queryId: "query-1-trake", numEvents: 3, items }),
  ]);
  // Dòng cuối của file chỉ có 2 frame -> phải báo đúng "Đáp án #3".
  assert.ok(
    issues.some((i) => /Đáp án #3 mới có 2\/3 frame/.test(i.msg)),
    `phải chỉ đúng khối cuối của FILE: ${JSON.stringify(issues.map((i) => i.msg))}`
  );
  assert.ok(
    !issues.some((i) => /Đáp án #4/.test(i.msg)),
    "không được báo khối không tồn tại trong file"
  );
});
test("TRAKE: frame không tăng dần vẫn bị bắt khi giỏ có mục hỏng", () => {
  // Sau khi lọc: [50, 30, 60] -> giảm ở giữa. Trước đây null làm lọt kiểm tra.
  const issues = validateSubmission([
    q({ taskType: "trake", queryId: "query-1-trake", numEvents: 3,
        items: [f("A", 50), f("A", null), f("A", 30), f("A", 60)] }),
  ]);
  assert.ok(
    issues.some((i) => /không tăng dần/.test(i.msg)),
    JSON.stringify(issues.map((i) => i.msg))
  );
});

test("hậu tố Query ID lệch task -> lỗi (file đúng tên nhưng sai số cột)", () => {
  const issues = validateSubmission([
    q({ qid: 3, taskType: "kis", queryId: "query-3-qa", items: [f("L01_V001", 10)] }),
  ]);
  assert.ok(
    issues.some((i) => i.level === "error" && /sai số cột/.test(i.msg)),
    JSON.stringify(issues.map((i) => i.msg))
  );
});
test("Q&A: khoảng trắng thừa và ngoặc kép tự gõ -> cảnh báo", () => {
  const padded = validateSubmission([
    q({ taskType: "qa", queryId: "query-1-qa", items: [f("L01_V001", 10, { answer: "Năm người " })] }),
  ]);
  assert.ok(!hasErrors(padded), JSON.stringify(padded));
  assert.ok(padded.some((i) => /khoảng trắng thừa/.test(i.msg)));

  const quoted = validateSubmission([
    q({ taskType: "qa", queryId: "query-1-qa", items: [f("L01_V001", 10, { answer: '"5"' })] }),
  ]);
  assert.ok(quoted.some((i) => /bọc trong dấu ngoặc kép/.test(i.msg)));
});
test("Q&A: answer 100 ký tự có dấu vẫn lọt (đếm theo code point)", () => {
  const issues = validateSubmission([
    q({ taskType: "qa", queryId: "query-1-qa", items: [f("L01_V001", 10, { answer: "ư".repeat(100) })] }),
  ]);
  assert.ok(!issues.some((i) => /vượt 100 ký tự/.test(i.msg)), JSON.stringify(issues.map((i) => i.msg)));
});
test("frame_idx không phải số nguyên -> lỗi", () => {
  const issues = validateSubmission([q({ items: [f("L01_V001", "25 300"), f("L01_V002", 12.5)] })]);
  assert.ok(
    issues.some((i) => i.level === "error" && /không phải số nguyên/.test(i.msg)),
    JSON.stringify(issues.map((i) => i.msg))
  );
  // Và cũng không được lọt vào file.
  assert.equal(toCSV([f("L01_V001", "25 300")], "kis"), "");
});
test("TRAKE: chung frame giữa hai ứng viên KHÔNG phải trùng", () => {
  // Hai chuỗi khác nhau, cùng đoán event 1 ở frame 10 -> hợp lệ, không được
  // báo "phí hạn mức".
  const issues = validateSubmission([
    q({ taskType: "trake", queryId: "query-1-trake", numEvents: 2,
        items: [f("A", 10), f("A", 20), { ...f("A", 10), id: "x1" }, f("A", 30)] }),
  ]);
  assert.ok(!issues.some((i) => /trùng/.test(i.msg)), JSON.stringify(issues.map((i) => i.msg)));
});
test("TRAKE: hai chuỗi giống hệt nhau -> cảnh báo phí hạn mức", () => {
  const issues = validateSubmission([
    q({ taskType: "trake", queryId: "query-1-trake", numEvents: 2,
        items: [f("A", 10), f("A", 20), { ...f("A", 10), id: "x1" }, { ...f("A", 20), id: "x2" }] }),
  ]);
  assert.ok(
    issues.some((i) => i.level === "warn" && /chuỗi trùng nhau hoàn toàn/.test(i.msg)),
    JSON.stringify(issues.map((i) => i.msg))
  );
});
test("có đáp án nhưng không mục nào xuất được -> lỗi, không im lặng mất file", () => {
  const issues = validateSubmission([q({ items: [f("L01_V001", null)] })]);
  assert.ok(issues.some((i) => i.level === "error" && /không mục nào xuất được/.test(i.msg)));
});
test("tên video lệch mẫu L**_V*** -> cảnh báo, không chặn", () => {
  const issues = validateSubmission([q({ items: [f("video_01", 10)] })]);
  assert.ok(!hasErrors(issues), JSON.stringify(issues.map((i) => i.msg)));
  assert.ok(issues.some((i) => i.level === "warn" && /không theo mẫu L01_V028/.test(i.msg)));
});

console.log("\n- Tên file nộp bám theo gói đề BTC -");
test("đổi task sau khi nạp gói KHÔNG đổi tên file nộp", () => {
  // Regression: "query-3-qa" khớp mẫu tự sinh nên set_task_type từng đổi nó
  // thành "query-3-kis" -> nộp ra một truy vấn không tồn tại.
  let state = normalize({ numQuestions: 3, questions: {} });
  state = applyOp(state, {
    type: "import_package",
    items: [{ qid: 3, taskType: "qa", queryId: "query-3-qa", queryText: "…", numEvents: null }],
  });
  assert.equal(state.questions[3].queryId, "query-3-qa");
  assert.equal(state.questions[3].queryIdLocked, true);

  state = applyOp(state, { type: "set_task_type", qid: 3, value: "kis" });
  assert.equal(state.questions[3].queryId, "query-3-qa", "tên BTC phát thì phải giữ nguyên");
  assert.equal(state.questions[3].taskType, "kis");
});
test("câu tự sinh (không nạp gói) vẫn đổi tên file theo task", () => {
  let state = normalize({ numQuestions: 2, questions: {} });
  state = applyOp(state, { type: "set_task_type", qid: 2, value: "trake" });
  assert.equal(state.questions[2].queryId, "query-2-trake");
});
test("gõ tay Query ID -> bỏ khoá, người dùng tự chịu trách nhiệm", () => {
  let state = normalize({ numQuestions: 1, questions: {} });
  state = applyOp(state, {
    type: "import_package",
    items: [{ qid: 1, taskType: "qa", queryId: "query-1-qa" }],
  });
  state = applyOp(state, { type: "set_query_id", qid: 1, value: "query-9-qa" });
  assert.equal(state.questions[1].queryIdLocked, false);
  state = applyOp(state, { type: "set_task_type", qid: 1, value: "kis" });
  // Hết khoá -> lại chạy theo luật cũ: tên tự sinh bám SỐ CÂU, không giữ số 9.
  assert.equal(state.questions[1].queryId, "query-1-kis");
});
test("nạp gói KHÔNG reset -> giữ đáp án và các câu ngoài gói", () => {
  let state = normalize({
    numQuestions: 4,
    questions: {
      1: { taskType: "kis", queryId: "query-1-kis", items: [{ id: "a" }] },
      4: { taskType: "qa", queryId: "query-4-qa", items: [{ id: "b" }] },
    },
  });
  state = applyOp(state, {
    type: "import_package",
    items: [{ qid: 1, taskType: "trake", queryId: "query-1-trake", numEvents: 3 }],
  });
  assert.equal(state.numQuestions, 4, "gộp thì số câu chỉ được phình ra");
  assert.deepEqual(state.questions[1].items.map((i) => i.id), ["a"]);
  assert.equal(state.questions[1].taskType, "trake");
  assert.ok(state.questions[4], "câu không nằm trong gói vẫn còn");
});
test("nhập lại từ đầu -> xoá cả câu đang bị ẩn ngoài phạm vi Số câu", () => {
  // Câu 6 của vòng trước không biến mất khi hạ numQuestions xuống 2, nó chỉ bị
  // ẩn (xem hiddenWithData). Nếu reset chỉ hạ số câu thì đáp án vòng trước sẽ
  // tái xuất ngay khi vòng sau có từ 6 câu, và lẫn vào zip nộp.
  let state = normalize({
    numQuestions: 2,
    questions: {
      1: { taskType: "kis", queryId: "query-1-kis", items: [{ id: "a" }] },
      6: { taskType: "qa", queryId: "query-6-qa", items: [{ id: "cu" }] },
    },
  });
  state = applyOp(state, {
    type: "import_package",
    reset: true,
    items: [{ qid: 1, taskType: "qa", queryId: "query-1-qa", queryText: "đề vòng 2" }],
  });
  assert.deepEqual(Object.keys(state.questions), ["1"]);
  assert.equal(state.numQuestions, 1, "số câu bám gói mới, không giữ số cũ");
  assert.equal(state.questions[1].items.length, 0);
  assert.equal(state.questions[1].queryId, "query-1-qa");
  assert.equal(state.questions[1].queryText, "đề vòng 2");
  assert.equal(state.questions[1].queryIdLocked, true);
});
test("queryIdLocked sống sót qua normalize (tải lại state)", () => {
  const state = normalize({
    numQuestions: 1,
    questions: { 1: { taskType: "qa", queryId: "query-1-qa", queryIdLocked: true, items: [] } },
  });
  assert.equal(state.questions[1].queryIdLocked, true);
});

console.log("\n- frame_idx -");
test("đọc frame_idx từ tên keyframe", () => {
  assert.equal(parseFrameNumber("000125.webp"), 125);
  assert.equal(parseFrameNumber("0.webp"), 0);
  assert.equal(parseFrameNumber("25300.jpg"), 25300);
});
test("KHÔNG bắt cụm số đầu tiên trong đường dẫn", () => {
  // Regression: /(\d+)/ trả về 1 cho "L01_V028/..." - một frame_idx trông hợp
  // lệ, sai hoàn toàn, và không validator nào bắt được vì nó khác null.
  assert.equal(parseFrameNumber("L01_V028/000125.webp"), 125);
  assert.equal(parseFrameNumber("L01_V028\\000125.webp"), 125);
});
test("tên không phải số -> null để rơi xuống fallback", () => {
  assert.equal(parseFrameNumber("keyframe_abc.webp"), null);
  assert.equal(parseFrameNumber("L01_V028.webp"), null);
  assert.equal(parseFrameNumber(null), null);
});
test("frameIndex fallback sang timestamp khi tên không đọc được", () => {
  assert.equal(frameIndex({ frame_name: "000125.webp", timestamp_ms: 999999, fps: 25 }), 125,
    "tên frame là nguồn chuẩn, không được để timestamp ghi đè");
  assert.equal(frameIndex({ frame_name: "abc.webp", timestamp_ms: 5000, fps: 25 }), 125);
  assert.equal(frameIndex({ frame_name: "abc.webp" }), null);
  assert.equal(frameIndex(null), null);
});

console.log("\n- Nhập gói đề BTC -");
test("phân tích tên file theo quy ước BTC", () => {
  assert.deepEqual(parseQueryFilename("query-1-kis.txt"), { qid: 1, taskType: "kis", queryId: "query-1-kis" });
  assert.deepEqual(parseQueryFilename("query-4-trake.txt"), { qid: 4, taskType: "trake", queryId: "query-4-trake" });
  assert.equal(parseQueryFilename("ghichu.txt"), null);
  assert.equal(parseQueryFilename("query-2-abc.txt"), null);
});
test("nhận tiền tố đợt thi và GIỮ NGUYÊN tên gốc làm Query ID", () => {
  // Gói thật (contest/THUNGHIEM-bo-de-thi.zip) đặt tên kèm đợt "p1". Dựng lại
  // thành "query-15-qa" là nộp file mang tên một truy vấn không tồn tại.
  assert.deepEqual(parseQueryFilename("query-p1-15-qa.txt"), { qid: 15, taskType: "qa", queryId: "query-p1-15-qa" });
  assert.deepEqual(parseQueryFilename("query-p1-16-trake.txt"), { qid: 16, taskType: "trake", queryId: "query-p1-16-trake" });
  assert.equal(parseQueryFilename("query-p1-15-qa (1).txt"), null, "bản tải trùng của trình duyệt không phải tên truy vấn hợp lệ");
  assert.equal(taskFromQueryId("query-p1-16-trake"), "trake");
  assert.equal(isAutoQueryId("query-p1-1-kis"), true);
  assert.equal(suggestFilename("query-p1-15-qa"), "query-p1-15-qa.csv");
});
test("đổi task giữ nguyên tiền tố đợt", () => {
  const s = applyOp({ numQuestions: 1, questions: {} }, {
    type: "import_package",
    items: [{ qid: 15, taskType: "qa", queryId: "query-p1-15-qa" }],
  });
  // Tên BTC phát -> bị khoá, đổi task cũng không được đụng tới.
  assert.equal(applyOp(s, { type: "set_task_type", qid: 15, value: "kis" }).questions[15].queryId, "query-p1-15-qa");
  // Gõ tay tên có tiền tố (không nạp gói) -> không khoá, tên tự đổi theo task
  // nhưng "p1" phải còn, nếu không file nộp mang tên truy vấn không tồn tại.
  let typed = applyOp({ numQuestions: 1, questions: {} }, { type: "set_task_type", qid: 15, value: "qa" });
  typed = applyOp(typed, { type: "set_query_id", qid: 15, value: "query-p1-15-qa" });
  assert.equal(applyOp(typed, { type: "set_task_type", qid: 15, value: "kis" }).questions[15].queryId, "query-p1-15-kis");
});
test("Query ID có tiền tố không còn bị báo sai mẫu", () => {
  const q = (taskType) => [{
    qid: 15, taskType, queryId: "query-p1-15-qa", maxRows: 100,
    items: [f("L01_V001", 10, { answer: "Vạn Ninh" })],
  }];
  assert.ok(!validateSubmission(q("qa")).some((i) => /không theo mẫu/.test(i.msg)));
  // Nhưng lệch task với tên file thì vẫn phải chặn.
  assert.ok(hasErrors(validateSubmission(q("kis"))), "tên file -qa mà câu đặt KIS -> sai số cột");
});
test("đoán số event từ đề TRAKE", () => {
  assert.equal(guessNumEvents("1. Vận động viên chạy đà\n2. Bật nhảy\n3. Qua xà\n4. Tiếp đất"), 4);
  assert.equal(guessNumEvents("Tìm cảnh có 3 người mặc áo đỏ."), null, "không bắt nhầm số trong câu văn");
  // Lối viết của đề thật (query-p1-16-trake.txt).
  assert.equal(guessNumEvents(
    "Đoạn video múa lân một con lân màu vàng đen trắng, tìm các sự kiện sau:\n" +
    "E1: Lân quay vòng trên cột số 4 bằng 2 chân trước rồi tiếp đất.\n" +
    "E2: Khoảnh khắc 4 chân hoàn toàn chạm đất đầu tiên.\n" +
    "E3: Khoảnh khắc đầu tiên 2 người biểu diễn lân cuối chào ban giám khảo.\n" +
    "E4: Sau đó lân tiến lại chào một con rồng."
  ), 4);
  assert.equal(guessNumEvents("E2: chỉ có một event lẻ\nE5: nhảy số"), null, "số event phải chạy liên tục 1..n");
});

// Đóng gói xong mới là thứ BTC thật sự nhận, mà nộp sai định dạng vẫn mất một
// trong ba lượt -> mở lại chính file zip vừa tạo và soi TỪNG BYTE, thay vì chỉ
// tin vào chuỗi mà toCSV trả về. Năm mục dưới đây bám đúng danh sách "lỗi
// thường gặp" của BTC: sai đuôi file, sai encoding, sai delimiter, có header,
// nén sai cấu trúc thư mục.
console.log("\n- Đóng gói .zip đúng chuẩn BTC -");
{
  const { default: JSZip } = await import("jszip");
  const questions = [
    { qid: 1, taskType: "kis", queryId: "query-p1-1-kis", maxRows: 100,
      items: [f("L01_V001", 1234), f("L02_V003", 55)] },
    { qid: 15, taskType: "qa", queryId: "query-p1-15-qa", maxRows: 100,
      items: [f("L21_V009", 900, { answer: "Vạn Ninh" }),
              f("L21_V009", 950, { answer: 'Xã "Đại Lãnh", Khánh Hoà' })] },
    { qid: 16, taskType: "trake", queryId: "query-p1-16-trake", maxRows: 100, numEvents: 4,
      items: [f("L30_V002", 10), f("L30_V002", 20), f("L30_V002", 30), f("L30_V002", 40)] },
  ];
  const blob = await buildSubmissionZip(buildExports(questions));
  const bytes = Buffer.from(await blob.arrayBuffer());
  const zip = await JSZip.loadAsync(bytes);
  const files = Object.values(zip.files).filter((e) => !e.dir);
  const raw = new Map();
  for (const e of files) raw.set(e.name, Buffer.from(await e.async("uint8array")));

  test("mọi file nằm trong thư mục submission/ ở gốc zip", () => {
    assert.deepEqual(files.map((e) => e.name).sort(), [
      "submission/query-p1-1-kis.csv",
      "submission/query-p1-15-qa.csv",
      "submission/query-p1-16-trake.csv",
    ]);
  });
  test("đuôi .csv, không phải .txt/.xlsx", () => {
    for (const name of raw.keys()) assert.ok(name.endsWith(".csv"), name);
  });
  test("UTF-8 KHÔNG BOM", () => {
    for (const [name, buf] of raw) {
      // BOM sẽ dính vào ô ĐẦU TIÊN của dòng đầu ("﻿L21_V009") và làm hỏng
      // phép so khớp chuỗi của BTC.
      assert.ok(!(buf[0] === 0xEF && buf[1] === 0xBB && buf[2] === 0xBF), `${name} có BOM`);
      const text = buf.toString("utf8");
      assert.ok(Buffer.from(text, "utf8").equals(buf), `${name} không phải UTF-8 hợp lệ`);
    }
  });
  test("tiếng Việt có dấu qua zip vẫn nguyên vẹn", () => {
    assert.equal(
      raw.get("submission/query-p1-15-qa.csv").toString("utf8").split("\n")[0],
      "L21_V009,900,Vạn Ninh"
    );
  });
  test("delimiter là dấu phẩy, không có header, không có CR", () => {
    for (const [name, buf] of raw) {
      const text = buf.toString("utf8");
      assert.ok(!text.includes("\r"), `${name} có CR - dòng sẽ thừa ký tự khi chấm`);
      assert.ok(!/\n$/.test(text), `${name} thừa dòng trống ở cuối`);
      assert.ok(!/^video|^Video/.test(text), `${name} có dòng header`);
      assert.ok(text.split("\n")[0].includes(","), `${name} không dùng dấu phẩy`);
    }
    // Dấu chấm phẩy chỉ được xuất hiện nếu chính đáp án có nó, không phải làm
    // delimiter -> mấy file này không có đáp án nào chứa ';'.
    for (const [name, buf] of raw) assert.ok(!buf.toString("utf8").includes(";"), name);
  });
  test("đáp án có dấu phẩy/ngoặc kép được bọc đúng RFC", () => {
    assert.equal(
      raw.get("submission/query-p1-15-qa.csv").toString("utf8").split("\n")[1],
      'L21_V009,950,"Xã ""Đại Lãnh"", Khánh Hoà"'
    );
  });
  test("TRAKE: mỗi ứng viên đúng MỘT dòng, đủ N cột", () => {
    const lines = raw.get("submission/query-p1-16-trake.csv").toString("utf8").split("\n");
    assert.equal(lines.length, 1);
    assert.equal(lines[0].split(",").length, 5); // video + 4 event
  });
}

test("Query ID lỡ kèm đuôi file -> KHÔNG sinh ra .txt.csv", () => {
  // Người dùng hay chép nguyên tên file trong gói đề vào ô Query ID.
  assert.equal(suggestFilename("query-p1-15-qa.txt"), "query-p1-15-qa.csv");
  assert.equal(suggestFilename("query-p1-15-qa.csv"), "query-p1-15-qa.csv");
  assert.equal(suggestFilename("query-p1-15-qa"), "query-p1-15-qa.csv");
});
test("frame_idx luôn ghi ra số nguyên", () => {
  // "1234.0" lọt qua isValidFrameIdx (trị số vẫn nguyên) nhưng ghi thẳng ra
  // file thì BTC so số nguyên sẽ không khớp.
  assert.equal(toCSV([f("L01_V001", "1234.0")], "kis"), "L01_V001,1234");
  assert.equal(toCSV([f("L01_V001", "0025")], "kis"), "L01_V001,25");
});
test("đáp án có xuống dòng không được xé một dòng CSV thành hai", () => {
  const csv = toCSV([f("L01_V001", 1, { answer: "dòng 1\ndòng 2" })], "qa");
  assert.equal(csv.split("\n").length, 1, "một đáp án phải ra đúng một dòng vật lý");
  assert.equal(csv, "L01_V001,1,dòng 1 dòng 2");
  const issues = validateSubmission([{
    qid: 1, taskType: "qa", queryId: "query-1-qa", maxRows: 100,
    items: [f("L01_V001", 1, { answer: "dòng 1\ndòng 2" })],
  }]);
  assert.ok(issues.some((i) => /xuống dòng/.test(i.msg)), "phải báo cho người dùng biết nội dung bị đổi");
});

console.log("\n- parseCsvLine (xem trước) -");
test("đọc lại đúng thứ toCSV vừa ghi ra", () => {
  assert.deepEqual(parseCsvLine("L01_V001,1234"), ["L01_V001", "1234"]);
  assert.deepEqual(parseCsvLine("L01_V001,1234,Vạn Ninh"), ["L01_V001", "1234", "Vạn Ninh"]);
});
test("đáp án có dấu phẩy vẫn ra ĐÚNG 3 cột", () => {
  // Đây là lý do màn xem trước phải tách cột thay vì cho nhìn văn bản thô: mắt
  // thường đọc dòng này ra 4 cột, chương trình chấm đọc ra 3.
  const csv = toCSV([f("L01_V001", 12, { answer: "Hà Nội, Việt Nam" })], "qa");
  assert.equal(csv, 'L01_V001,12,"Hà Nội, Việt Nam"');
  assert.deepEqual(parseCsvLine(csv), ["L01_V001", "12", "Hà Nội, Việt Nam"]);
});
test("ngoặc kép trong đáp án được gỡ về đúng một dấu", () => {
  const csv = toCSV([f("L01_V001", 12, { answer: 'phim "Mắt Biếc"' })], "qa");
  assert.deepEqual(parseCsvLine(csv), ["L01_V001", "12", 'phim "Mắt Biếc"']);
});
test("TRAKE: mỗi dòng ra đúng N+1 cột", () => {
  const csv = toCSV([f("L01_V001", 10), f("L01_V001", 20), f("L01_V001", 30)], "trake", { numEvents: 3 });
  assert.deepEqual(parseCsvLine(csv), ["L01_V001", "10", "20", "30"]);
});

console.log("\n- set_frame (sửa tay số frame) -");
// Giỏ một câu, một mục - đủ cho mọi khẳng định dưới đây.
const oneItem = (extra = {}) => normalize({
  numQuestions: 1,
  questions: { 1: { items: [{ id: "X", video_name: "L01_V001", frame_name: "000100.webp", frame_idx: 100, timestamp_ms: 4000, fps: 25, ...extra }] } },
});
const itemOf = (st) => st.questions[1].items[0];

test("ghi frame mới và tính lại timestamp theo fps", () => {
  const next = applyOp(oneItem(), { type: "set_frame", qid: 1, id: "X", value: 137 });
  assert.equal(itemOf(next).frame_idx, 137);
  assert.equal(itemOf(next).timestamp_ms, 5480, "137/25*1000 - mọi nút mở video tua theo trường này");
});
test("frame_name GIỮ NGUYÊN", () => {
  // /frame_neighbors tra theo tên keyframe; đổi nó là hỏng nút 'chuỗi'.
  const next = applyOp(oneItem(), { type: "set_frame", qid: 1, id: "X", value: 137 });
  assert.equal(itemOf(next).frame_name, "000100.webp");
});
test("không có fps -> chỉ đổi frame, không bịa timestamp", () => {
  const next = applyOp(oneItem({ fps: null }), { type: "set_frame", qid: 1, id: "X", value: 137 });
  assert.equal(itemOf(next).frame_idx, 137);
  assert.equal(itemOf(next).timestamp_ms, 4000);
});
test("frame_idx0 chỉ ghi ở LẦN SỬA ĐẦU", () => {
  let st = applyOp(oneItem(), { type: "set_frame", qid: 1, id: "X", value: 137 });
  st = applyOp(st, { type: "set_frame", qid: 1, id: "X", value: 150 });
  assert.equal(itemOf(st).frame_idx0, 100, "sửa hai lần vẫn phải hoàn tác về số máy tự tính");
  // Hoàn tác = gửi lại chính frame_idx0.
  st = applyOp(st, { type: "set_frame", qid: 1, id: "X", value: itemOf(st).frame_idx0 });
  assert.equal(itemOf(st).frame_idx, 100);
});
test("giá trị rác KHÔNG lọt vào giỏ dùng chung", () => {
  // frame_idx rác làm mục này bị loại âm thầm khỏi file nộp -> reducer phải trả
  // về CHÍNH state cũ, không phải một bản sao.
  const st = oneItem();
  // "" và null là bẫy riêng: Number() biến cả hai thành 0 - một frame_idx trông
  // hoàn toàn hợp lệ. Ô nhập để trống phải là "không đổi gì", không phải "frame 0".
  for (const bad of ["abc", "", null, undefined, true, -5, NaN]) {
    assert.equal(applyOp(st, { type: "set_frame", qid: 1, id: "X", value: bad }), st, `giá trị ${bad}`);
  }
});
test("số thực được làm tròn về frame gần nhất", () => {
  // Không phải giá trị rác: dữ liệu cũ trong giỏ có thể mang "1234.0" (xem
  // frameCell), và một frame lẻ 1.5 thì chỉ có đúng một cách hiểu.
  const st = oneItem();
  assert.equal(itemOf(applyOp(st, { type: "set_frame", qid: 1, id: "X", value: "137.0" })).frame_idx, 137);
  assert.equal(itemOf(applyOp(st, { type: "set_frame", qid: 1, id: "X", value: 136.5 })).frame_idx, 137);
});
test("gõ lại đúng số cũ / id không tồn tại -> không đổi gì", () => {
  const st = oneItem();
  assert.equal(applyOp(st, { type: "set_frame", qid: 1, id: "X", value: 100 }), st);
  assert.equal(applyOp(st, { type: "set_frame", qid: 1, id: "KHONG_CO", value: 137 }), st);
});
test("frame sửa tay đi thẳng vào CSV", () => {
  const st = applyOp(oneItem(), { type: "set_frame", qid: 1, id: "X", value: 137 });
  assert.equal(toCSV(st.questions[1].items, "kis"), "L01_V001,137");
});

console.log("\n- Thêm frame thủ công -");
test("frame nộp lấy theo tên frame MÌNH GÕ, không theo keyframe gần nhất", () => {
  // ManualFrameAdd dựng result với frame_name = số người dùng gõ và frame_idx0
  // = keyframe gần nhất (cái ảnh sẽ hiện trong giỏ).
  const e = toEntry({
    id: "manual:L29_V001_9211", video_name: "L29_V001", frame_name: "009211.webp",
    timestamp_ms: 368440, fps: 25, frame_idx0: 9185,
  });
  assert.equal(e.frame_idx, 9211, "số nộp là số đã gõ");
  assert.equal(e.frame_idx0, 9185, "ảnh đang hiện là keyframe này -> giỏ vẽ badge Δ+26");
  assert.equal(toCSV([e], "kis"), "L29_V001,9211");
});
test("mục thêm bằng nút + KHÔNG mọc frame_idx0", () => {
  // Ảnh chính là frame sẽ nộp -> không có gì để cảnh báo lệch.
  const e = toEntry({ id: "L29_V001_9185", video_name: "L29_V001", frame_name: "009185.webp", fps: 25 });
  assert.ok(!("frame_idx0" in e));
});

console.log(`\n${pass} test đã qua.\n`);
