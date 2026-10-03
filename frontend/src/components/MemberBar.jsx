// src/components/MemberBar.jsx
// Ai đang online, đang làm câu mấy, và kết nối phòng còn sống không.
//
// "Đang làm câu mấy" là thứ chống giẫm chân rẻ nhất mà hiệu quả nhất: 5 người
// nhìn một chỗ là biết câu nào chưa ai đụng, khỏi phải hô nhau.
//
// HÌNH DÁNG: MỘT viên thuốc duy nhất, các phần ngăn nhau bằng vạch tóc bên
// trong. Trước đây trạng thái / hàng đợi / avatar là ba khối rời trôi cạnh nhau
// ở ba chiều cao khác nhau (32px, 32px, 28px) nên góc phải header trông lổn
// nhổn. Gộp lại còn một khối cao 36px = đúng chiều cao nút icon bên cạnh, cả
// hàng ăn chung một đường baseline.
//
// MÀU: bình thường thì TRUNG TÍNH (viền xám, chấm xanh nhỏ) - màu nền chỉ dành
// cho việc cần để ý (mất kết nối = hổ phách). Cả buổi thi ngồi cạnh một mảng
// xanh lá không nói thêm được gì; còn khi phòng rớt, mảng hổ phách đập vào mắt
// ngay. Cùng lý do với chấm xanh đứng yên: chuyển động chỉ để dành cho ⟳.
//
// Ba trạng thái RỜI NHAU, đừng gộp:
//   - chưa vào phòng (bật chế độ phòng nhưng chưa chọn tên): không phải mất
//     mạng, chỉ là chưa nối - trước đây cũng hiện "Offline" nên gây hiểu nhầm;
//   - đang nối lần đầu: cũng từng bị vẽ thành "Offline" trong khoảnh khắc bắt
//     tay, làm người dùng tưởng backend chết;
//   - online: socket đang mở;
//   - mất kết nối: số thao tác đang chờ gửi nằm ở NGĂN RIÊNG có nhãn ⟳ - trước
//     đây nó đứng ngay cạnh chữ "Offline", đúng chỗ mà lúc online là số người,
//     nên đọc thành "2 người đang offline".
import { UsersIcon, WifiOffIcon, RefreshIcon } from "./Icons";
import { resolveRoomBaseUrl, roomBaseSource } from "../api/roomClient";
import { initials, memberColor } from "../utils/memberStyle";

// "Mất kết nối" mà không nói đang gọi vào ĐÂU, và cái ĐÂU đó do AI đặt, thì
// không chẩn được. Hai lỗi đã gặp thật, cả hai đều nhìn y hệt nhau trên badge:
//   - chưa đặt Room URL -> client ăn theo Backend URL, gõ cửa cổng không có ai;
//   - localStorage còn giữ URL tunnel của buổi trước -> nó ĐÈ LÊN .env vừa sửa,
//     sửa file bao nhiêu lần cũng không ăn thua.
// Nguồn mới là thứ chỉ ra phải đi sửa ở đâu, chứ không phải bản thân cái host.
const SOURCE_NOTE = {
  settings: "đặt tay trong Cài đặt ⚙ - xoá trống ô đó để quay về mặc định",
  env: "từ VITE_ROOM_BASE_URL trong frontend/.env",
  backend: "đang ăn theo Backend URL vì chưa đặt Room URL",
};

// Đọc thẳng trong thân render, không cache: hai hàm này chỉ sờ localStorage /
// import.meta.env nên rẻ, mà cache lại thì tooltip nói host cũ ngay sau khi
// người dùng vừa đổi trong Cài đặt (⚙).
function roomTarget() {
  return `${resolveRoomBaseUrl()} - ${SOURCE_NOTE[roomBaseSource()]}`;
}

// Vạch ngăn giữa các ngăn trong cùng viên thuốc: cao bằng ~2/3 pill, canh giữa.
const Divider = ({ className = "" }) => (
  <span aria-hidden className={`mx-0.5 h-5 w-px shrink-0 bg-current opacity-15 ${className}`} />
);

function MemberBar({ room }) {
  if (!room.enabled) return null;

  const { status, members, member } = room;
  const joined = !!member;
  const online = joined && status.connected;
  const connecting = joined && !online && status.connecting && !status.everConnected;
  const pending = status.pending || 0;
  const offline = joined && !online && !connecting;

  const tone = offline
    ? "border-amber-300 bg-amber-50 text-amber-800"
    : online
      ? "border-slate-200 bg-white text-slate-600"
      : "border-slate-200 bg-slate-50 text-slate-500";

  const title = !joined
    ? "Chế độ phòng đang bật nhưng chưa chọn tên - chọn tên để nối vào phòng."
    : connecting
      ? `Đang nối vào phòng (${roomTarget()})…`
      : online
        ? `Đã nối phòng - ${members.length} người đang online${pending ? `, còn ${pending} thao tác đang gửi` : ""}.`
        : `Mất kết nối tới phòng (${roomTarget()}). Vẫn làm việc bình thường - thao tác đang xếp hàng và sẽ tự đồng bộ khi phòng trở lại.`;

  return (
    <div
      className={`inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full border pl-2.5 pr-1.5 text-xs font-semibold transition-colors ${tone}`}
      title={title}
    >
      {/* --- Ngăn 1: trạng thái --- */}
      {!joined ? (
        <>
          <span className="h-2 w-2 shrink-0 rounded-full bg-slate-300" />
          <span className="hidden pr-1 sm:inline">Chưa vào phòng</span>
        </>
      ) : connecting ? (
        <>
          <RefreshIcon className="h-3.5 w-3.5 shrink-0 animate-spin" />
          <span className="hidden pr-1 sm:inline">Đang nối…</span>
        </>
      ) : offline ? (
        <>
          <WifiOffIcon className="h-4 w-4 shrink-0" />
          <span className="hidden pr-1 sm:inline">Mất kết nối</span>
        </>
      ) : (
        <>
          {/* Chấm xanh ĐỨNG YÊN - xem ghi chú đầu file. */}
          <span className="h-2 w-2 shrink-0 rounded-full bg-emerald-500 ring-2 ring-emerald-500/20" />
          {/* Con số này CHỈ hiện khi chưa đủ chỗ vẽ avatar: có avatar rồi thì
              đếm đầu người bằng mắt, in thêm số là nói hai lần một chuyện. */}
          <span className="tabular-nums md:hidden">{members.length}</span>
          <UsersIcon className="h-3.5 w-3.5 shrink-0 opacity-60 md:hidden" />
        </>
      )}

      {/* --- Ngăn 2: hàng đợi ---
          Hiện ở CẢ hai trạng thái: đang online mà queue chưa xả hết (backend
          nhận chậm / lỗi 5xx) cũng là điều phải biết trước khi tắt máy.
          Quay = đang gửi, đứng yên = đang chờ mạng về. */}
      {joined && pending > 0 && (
        <>
          <Divider />
          <span
            className={`inline-flex items-center gap-1 tabular-nums ${offline ? "text-amber-800" : "text-slate-500"}`}
            title={`${pending} thao tác chưa gửi được lên phòng - đã lưu máy này, sẽ tự gửi khi phòng trở lại. Đừng tắt trình duyệt khi còn số này.`}
          >
            <RefreshIcon className={`h-3.5 w-3.5 ${online ? "animate-spin" : ""}`} />
            {pending}
          </span>
        </>
      )}

      {/* --- Ngăn 3: ai đang làm câu nào ---
          Avatar chỉ có nghĩa khi socket còn mở: mất kết nối thì danh sách này là
          ảnh chụp lúc rớt mạng, nên làm xám lại để không đọc nhầm là hiện tại.

          KHÔNG chồng mép avatar lên nhau: mỗi avatar đeo một chip số ở góc phải,
          chồng lên là con số của người đứng trước bị người sau che mất đúng nửa
          - mà con số mới là thông tin, avatar chỉ là nhãn. Cách nhau 4px vẫn
          đọc ra "một nhóm". */}
      {joined && members.length > 0 && (
        <>
          {/* Vạch ngăn theo cùng breakpoint với avatar, không thì màn hình hẹp
              còn trơ một sợi kẻ chẳng ngăn cái gì. */}
          <Divider className="hidden md:block" />
          <div
            className={`hidden items-center gap-2 pr-0.5 transition md:flex ${online ? "" : "opacity-40 grayscale"}`}
            title={online ? undefined : "Danh sách lúc còn kết nối - chưa chắc còn đúng"}
          >
            {members.map((m) => (
              // Số câu nằm CẠNH avatar, không đè lên. Kiểu chip-ở-góc quen thuộc
              // (badge thông báo) chỉ hợp khi nội dung là một chấm hoặc một chữ
              // số ít quan trọng hơn thứ nó đè; ở đây ngược lại - số câu mới là
              // cái phải đọc, mà chip 16px trên avatar 28px che mất quá nửa chữ
              // viết tắt, hỏng cả hai đằng.
              //
              // Ghép cặp bằng KHOẢNG CÁCH: trong cặp 2px, giữa các cặp 8px. Mắt
              // tự gom đúng số về đúng người mà không cần khung hay vạch nào.
              <span
                key={m.id}
                title={`${m.name}${m.id === member?.id ? " (bạn)" : ""} - đang làm câu ${m.current}`}
                className="inline-flex items-center gap-0.5"
              >
                <span
                  className={`flex h-7 w-7 items-center justify-center rounded-full text-[10px] font-bold text-white ring-2 ${memberColor(m.name)} ${
                    // Vòng ring của CHÍNH MÌNH đổi màu thay vì dày thêm: dày thêm
                    // sẽ đội avatar lên cao hơn hàng, phá mất chiều cao chung.
                    m.id === member?.id ? "ring-blue-500" : "ring-white"
                  }`}
                >
                  {initials(m.name)}
                </span>
                <span className="text-[11px] font-bold leading-none tabular-nums text-slate-500">
                  {m.current}
                </span>
              </span>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

export default MemberBar;
