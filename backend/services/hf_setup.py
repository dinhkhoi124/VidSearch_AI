"""Cấu hình HuggingFace Hub (đăng nhập + tăng tốc tải) trước khi nạp model.

LƯU Ý cho khỏi kỳ vọng sai: **token KHÔNG tự làm băng thông nhanh hơn**. Token
cho hai thứ khác:
  * quyền tải repo gated (SigLIP2 của Google từng đòi chấp nhận điều khoản)
  * hạn mức request cao hơn - quan trọng trên Colab vì hàng nghìn notebook dùng
    chung dải IP, request ẩn danh bị siết trước và hay dính 429 giữa chừng.

Thứ THỰC SỰ làm tải nhanh, xếp theo mức ăn thua:
  1. HF_HOME trỏ vào chỗ lưu bền (Google Drive) - lần chạy sau không tải lại gì
     cả. Colab xoá /root/.cache mỗi session; đây là khác biệt lớn nhất.
  2. hf_xet - backend Xet của hub >= 0.32, tải theo chunk và dedup; repo nào đã
     chuyển sang Xet thì đây là đường nhanh nhất, chỉ cần cài gói `hf_xet`.
  3. hf_transfer - downloader Rust đa luồng cho repo chưa lên Xet. Đổi lại:
     mất thanh tiến trình và mất retry mềm, nên tắt được bằng cấu hình.

Module này PHẢI chạy trước khi bất cứ thứ gì import `huggingface_hub`: gói đó
đọc các biến môi trường một lần lúc import, đặt muộn hơn là vô tác dụng.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict

from config import get_settings

settings = get_settings()

_report: Dict[str, Any] = {"configured": False}


def get_report() -> Dict[str, Any]:
    """Kết quả lần cấu hình gần nhất (dùng cho báo cáo warm-up)."""
    return dict(_report)


def _already_imported() -> bool:
    return "huggingface_hub" in sys.modules


def _enable_hf_transfer() -> str:
    if not settings.hf_enable_transfer:
        return "tắt theo cấu hình"
    try:
        import hf_transfer  # noqa: F401
    except ImportError:
        return "chưa cài (pip install hf_transfer)"
    os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
    return "bật"


def _xet_status() -> str:
    try:
        import hf_xet  # noqa: F401
    except ImportError:
        return "chưa cài (pip install hf_xet)"
    return "có sẵn"


def _apply_token() -> str:
    """Đưa token vào môi trường + kiểm chứng bằng whoami. Không ghi ra đĩa."""
    token = (settings.hf_token or "").strip()
    if not token:
        # Người dùng có thể đã `huggingface-cli login` từ trước -> token nằm sẵn
        # trong cache; đừng ghi đè, chỉ báo lại tình trạng.
        if os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN"):
            return "dùng token có sẵn trong môi trường"
        return "ẩn danh (không có HF_TOKEN) - dễ bị siết hạn mức trên Colab"

    os.environ["HF_TOKEN"] = token
    os.environ["HUGGING_FACE_HUB_TOKEN"] = token  # tên cũ, vài lib vẫn đọc
    return "đã đặt token"


def _whoami() -> str:
    """Kiểm chứng token thật sự dùng được. Lỗi mạng không được chặn boot."""
    try:
        from huggingface_hub import whoami

        info = whoami()
        return f"đăng nhập: {info.get('name') or info.get('fullname') or '?'}"
    except Exception as e:  # noqa: BLE001 - offline/token sai vẫn phải chạy tiếp
        return f"không xác thực được ({type(e).__name__}) - vẫn tải được repo công khai"


def configure_hf(verify: bool = True) -> Dict[str, Any]:
    """Đặt HF_HOME / token / tăng tốc tải. Gọi lại nhiều lần vẫn an toàn."""
    global _report

    late = _already_imported()

    home = (settings.hf_home or "").strip()
    if home:
        os.environ["HF_HOME"] = home
        os.makedirs(home, exist_ok=True)
        home_status = home
    else:
        home_status = os.environ.get("HF_HOME") or "mặc định (~/.cache/huggingface)"

    if settings.hf_download_timeout > 0:
        os.environ.setdefault(
            "HF_HUB_DOWNLOAD_TIMEOUT", str(settings.hf_download_timeout)
        )

    token_status = _apply_token()
    transfer_status = _enable_hf_transfer()
    xet_status = _xet_status()

    _report = {
        "configured": True,
        "cache_dir": home_status,
        "token": token_status,
        "hf_transfer": transfer_status,
        "hf_xet": xet_status,
        "late_import": late,
    }
    if verify:
        _report["auth"] = _whoami()

    print(
        f"[hf] cache={home_status} | {token_status} | "
        f"hf_transfer={transfer_status} | hf_xet={xet_status}"
        + (f" | {_report['auth']}" if verify else "")
    )
    if late:
        # Đặt biến sau khi hub đã import thì HF_HOME / HF_HUB_ENABLE_HF_TRANSFER
        # không còn tác dụng - nói thẳng thay vì để người dùng tưởng đã bật.
        print("[hf] CẢNH BÁO: huggingface_hub đã được import trước khi cấu hình - "
              "HF_HOME và hf_transfer sẽ KHÔNG có hiệu lực trong tiến trình này")
    return get_report()
