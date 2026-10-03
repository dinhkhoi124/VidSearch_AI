// src/components/ResultGallery.jsx
// Gallery DÙNG CHUNG cho mọi loại truy vấn (text/image/ocr/asr/temporal/agent/feedback).
// Nhận thẳng danh sách kết quả ĐÃ LÀM PHẲNG (xem utils/flattenResults.js) nên
// bấm vào ảnh ở bất kỳ chế độ nào cũng ra cùng một trải nghiệm:
//   dải thumbnail để lướt · tiêu đề cho biết frame nằm ở mốc nào của video ·
//   nút Thêm vào giỏ · nút Xem video tại đúng đoạn · nút xem chuỗi frame.
import { useMemo } from "react";
import Lightbox, { IconButton } from "yet-another-react-lightbox";
import Zoom from "yet-another-react-lightbox/plugins/zoom";
import Captions from "yet-another-react-lightbox/plugins/captions";
import Counter from "yet-another-react-lightbox/plugins/counter";
import Thumbnails from "yet-another-react-lightbox/plugins/thumbnails";
import "yet-another-react-lightbox/styles.css";
import "yet-another-react-lightbox/plugins/captions.css";
import "yet-another-react-lightbox/plugins/counter.css";
import "yet-another-react-lightbox/plugins/thumbnails.css";

import { frameIndex, fmtTime } from "../utils/frameIndex";
import { PlayIcon, FilmIcon, PlusIcon } from "./Icons";

// Dòng mô tả dưới ảnh: ưu tiên bằng chứng của chính chế độ tìm kiếm đó.
function describe(r) {
  const parts = [];
  if (r.event_index != null) parts.push(`Event ${r.event_index + 1}`);
  if (typeof r.score === "number") parts.push(`score ${r.score.toFixed(3)}`);
  const head = parts.join(" · ");
  const asr = (r.asr_text || "").trim();
  return [head, asr && `“${asr}”`].filter(Boolean).join(" - ");
}

function ResultGallery({
  results,          // danh sách phẳng, cùng thứ tự với lưới
  index,
  open,
  onClose,
  onIndexChange,
  onVideoClick,
  onFramesClick,
  onToggleBasket,
  basketRankOf,
  currentQuestion,
}) {
  // Danh sách có thể tới hàng nghìn ảnh và parent re-render liên tục (giỏ, đã
  // xem, focus) -> chỉ dựng lại slides khi chính danh sách kết quả đổi.
  const slides = useMemo(
    () =>
      results.map((r) => ({
        src: r.frame_url,
        title: `${r.video_name} · frame ${frameIndex(r) ?? "?"} · ${fmtTime(r.timestamp_ms)}`,
        description: describe(r),
      })),
    [results]
  );

  // Các nút thanh công cụ luôn tác động lên slide ĐANG HIỆN, nhờ `index` được
  // parent đồng bộ qua on.view.
  const current = results[index];
  const rank = current && basketRankOf ? basketRankOf(current.id) : null;
  const inBasket = rank != null;

  // Mở modal khác thì đóng gallery trước: lightbox bắt phím mũi tên/Esc ở phạm
  // vi toàn cục nên chồng modal lên trên sẽ tranh phím. `index` vẫn giữ nguyên
  // nên bấm `z` là quay lại đúng ảnh đang xem dở.
  const handoff = (fn) => () => {
    if (!current) return;
    onClose();
    fn(current);
  };

  const buttons = [
    <IconButton
      key="basket"
      label={
        inBasket
          ? `Bỏ khỏi giỏ câu ${currentQuestion ?? ""} (đang hạng ${rank})`
          : `Thêm vào giỏ đáp án câu ${currentQuestion ?? ""}`
      }
      icon={PlusIcon}
      renderIcon={
        inBasket
          ? () => (
              <span className="px-1.5 text-sm font-bold tabular-nums text-emerald-400">#{rank}</span>
            )
          : undefined
      }
      onClick={() => current && onToggleBasket(current)}
      disabled={!current}
    />,
    <IconButton
      key="video"
      label="Xem video tại đoạn này"
      icon={PlayIcon}
      onClick={handoff(onVideoClick)}
      disabled={!current}
    />,
    <IconButton
      key="frames"
      label="Xem các frame liên tiếp"
      icon={FilmIcon}
      onClick={handoff(onFramesClick)}
      disabled={!current}
    />,
    "close",
  ];

  return (
    <Lightbox
      open={open}
      close={onClose}
      slides={slides}
      index={index}
      on={{ view: ({ index: i }) => onIndexChange(i) }}
      toolbar={{ buttons }}
      plugins={[Zoom, Captions, Counter, Thumbnails]}
      captions={{ descriptionTextAlign: "center" }}
      thumbnails={{ width: 96, height: 54, border: 0, gap: 6, padding: 0, imageFit: "cover" }}
      zoom={{
        maxZoomPixelRatio: 5,
        zoomInMultiplier: 1.4,
        doubleTapDelay: 300,
        doubleClickDelay: 300,
        doubleClickMaxStops: 2,
        keyboardMoveDistance: 50,
      }}
    />
  );
}

export default ResultGallery;
