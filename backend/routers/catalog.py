"""Danh mục backbone visual mà backend NÀY thực sự chạy được.

Giao diện trước đây hardcode danh sách model trong frontend/src/constants/models.js
và phải sửa tay mỗi lần build thêm index. Hệ quả là hai kiểu lệch, cả hai đều
tốn hàng giờ mới truy ra:

  - Danh sách THIẾU model đã có index (siglip512, metaclip): công sức build index
    nằm không, không ai chọn được từ UI.
  - Danh sách THỪA model chưa có index: chọn vào là 503 giữa lúc thi.

Nguồn sự thật duy nhất là đĩa của backend: `data/indexes/<model>.index`. Endpoint
này đọc thẳng ở đó, FE chỉ việc hiển thị. Máy nào chạy backend nấy — đồng đội cắm
vào backend khác thì danh sách tự đổi theo.
"""
from fastapi import APIRouter

from config import get_settings
from services.embedding_service import backbone_catalog
from services.ensemble_service import parse_ensemble_models

router = APIRouter()
settings = get_settings()


def _has_index(model: str) -> bool:
    return (settings.data_path / "indexes" / f"{model}.index").exists()


@router.get("/models")
def list_models():
    """Model visual dùng được + cấu hình ensemble hiện tại của backend."""
    catalog = backbone_catalog()
    models = [
        {
            "value": name,
            "hf": info["hf"],
            "dim": info["dim"],
            "has_index": _has_index(name),
        }
        for name, info in sorted(catalog.items())
    ]

    members = [
        {"model": name, "weight": weight, "has_index": _has_index(name)}
        for name, weight in parse_ensemble_models()
    ]
    return {
        "default": settings.default_model,
        # Ensemble tự bỏ qua member thiếu index (xem ensemble_service); chỉ khi
        # KHÔNG member nào còn index thì chọn "ensemble" mới chắc chắn 503.
        "ensemble": {
            "members": members,
            "available": any(m["has_index"] for m in members),
        },
        "models": models,
    }
