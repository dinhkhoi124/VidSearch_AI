"""Smoke test cho phòng thi nhóm - chạy KHÔNG cần nạp model.

    python scripts/room_smoke.py

Dựng một FastAPI chỉ gắn router `room` (router này không import service model
nào, nên chạy trong vài giây thay vì ~2 phút warm-up), rồi kiểm 5 điều dễ hỏng
nhất khi 5 người dùng chung một giỏ:

  1. hai client cùng nhận được broadcast, cùng một chuỗi rev;
  2. hai người thêm xen kẽ vào CÙNG một câu -> không mất frame nào, thứ tự khớp;
  3. op lặp lại (replay sau khi mất mạng) không nhân đôi;
  4. reorder/move ra đúng thứ tự;
  5. snapshot sống sót qua restart;
  6. presence gộp nhiều tab của một người ra kết quả KHÔNG đổi theo thứ tự duyệt.
"""
import itertools
import json
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

# Cùng lý do với main.py và room_server.py: console Windows mặc định cp1252 nên
# chỉ một chữ "nhận" trong tiêu đề mục [1] là UnicodeEncodeError - smoke test
# chết ở dòng print ĐẦU TIÊN, trước khi kiểm được điều gì, và traceback lại nói
# về codec chứ không nói về phòng.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def build_app(tmp: Path):
    """Mỗi lần gọi tạo store mới trỏ vào tmp - mô phỏng restart backend.

    Lifespan phải GIỐNG main.py (load lúc bật, flush lúc tắt): snapshot ghi theo
    kiểu debounce nên thao tác cuối cùng chỉ xuống đĩa nhờ cú flush khi tắt. Bỏ
    lifespan ở đây thì bước [8] kiểm tra một luồng không tồn tại trong thực tế.
    """
    import routers.room as room_mod
    from services.agent_history_store import AgentHistoryStore
    from services.room_hub import RoomHub
    from services.room_store import RoomStore

    room_mod.store = RoomStore(path=tmp / "room-default.json", history_max=200, debounce_s=0.01)
    room_mod.hub = RoomHub()
    # Trần thấp hơn mặc định để bước [6d] chạm được vào cả ba đường cắt (số cuộc,
    # số frame mỗi lượt, số lượt còn giữ frame) mà không phải bơm hàng chục lượt.
    room_mod.agent_history = AgentHistoryStore(
        root=tmp / "agent-history", max_chats=2, result_cap=2, payload_turns=2, debounce_s=0.01,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        room_mod.store.load()
        yield
        await room_mod.store.flush()
        await room_mod.agent_history.flush()

    app = FastAPI(lifespan=lifespan)
    app.include_router(room_mod.router)
    return app, room_mod


def item(fid: str, video: str = "L01_V001", idx: int = 1):
    return {"id": fid, "video_name": video, "frame_idx": idx, "frame_name": f"{idx:06d}.webp"}


def op(client, member_id, member_name, body):
    r = client.post("/room/op", json={"member_id": member_id, "member_name": member_name, "op": body})
    assert r.status_code == 200, r.text
    return r.json()


def drain(ws, expect):
    """Đọc đúng `expect` message, bỏ qua presence (thời điểm tới không xác định)."""
    out = []
    while len(out) < expect:
        msg = ws.receive_json()
        if msg.get("type") == "presence":
            continue
        out.append(msg)
    return out


def main():
    failures = []

    def check(name, cond, detail=""):
        print(f"  {'PASS' if cond else 'FAIL'}  {name}{'' if cond else '  <- ' + detail}")
        if not cond:
            failures.append(name)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        app, room_mod = build_app(tmp)

        print("\n[1] Hai client cùng nhận broadcast")
        with TestClient(app) as client:
            with client.websocket_connect("/room/ws?member_id=a&member_name=An") as wa, \
                 client.websocket_connect("/room/ws?member_id=b&member_name=Binh") as wb:
                snap_a = wa.receive_json()
                snap_b = wb.receive_json()
                check("snapshot lúc connect", snap_a["type"] == "snapshot" and snap_b["type"] == "snapshot")

                print("\n[2] Thêm xen kẽ vào CÙNG câu 3 -> không mất frame, thứ tự khớp")
                for i in range(6):
                    who = ("a", "An") if i % 2 == 0 else ("b", "Binh")
                    op(client, who[0], who[1], {"type": "add", "qid": 3, "item": item(f"f{i}", idx=i)})

                msgs_a = drain(wa, 6)
                msgs_b = drain(wb, 6)
                revs_a = [m["rev"] for m in msgs_a]
                revs_b = [m["rev"] for m in msgs_b]
                check("cùng chuỗi rev", revs_a == revs_b, f"{revs_a} vs {revs_b}")
                check("rev tăng đơn điệu", revs_a == sorted(set(revs_a)), str(revs_a))

                ids_a = [it["id"] for it in msgs_a[-1]["question"]["items"]]
                ids_b = [it["id"] for it in msgs_b[-1]["question"]["items"]]
                check("đủ 6 frame, không mất", ids_a == [f"f{i}" for i in range(6)], str(ids_a))
                check("hai máy thấy cùng thứ tự", ids_a == ids_b)

                owners = [it["added_by_name"] for it in msgs_a[-1]["question"]["items"]]
                check("ghi đúng ai thêm", owners == ["An", "Binh"] * 3, str(owners))

                print("\n[3] Replay op sau khi mất mạng -> không nhân đôi")
                res = op(client, "a", "An", {"type": "add", "qid": 3, "item": item("f0", idx=0)})
                check("add trùng id bị bỏ qua", res["applied"] is False, str(res))

                print("\n[4] Sắp xếp lại")
                op(client, "b", "Binh", {"type": "move", "qid": 3, "id": "f5", "dir": -1})
                m = drain(wa, 1)[0]
                ids = [it["id"] for it in m["question"]["items"]]
                check("move -1 đổi chỗ f4/f5", ids == ["f0", "f1", "f2", "f3", "f5", "f4"], str(ids))

                op(client, "a", "An", {"type": "reorder", "qid": 3, "from": 0, "to": 5})
                m = drain(wa, 1)[0]
                ids = [it["id"] for it in m["question"]["items"]]
                check("reorder 0->5", ids == ["f1", "f2", "f3", "f5", "f4", "f0"], str(ids))

                print("\n[5] Op không đổi gì -> không broadcast")
                res = op(client, "a", "An", {"type": "set_task_type", "qid": 3, "value": "kis"})
                check("set lại đúng giá trị cũ -> applied=False", res["applied"] is False, str(res))

                print("\n[6] Lịch sử nhóm")
                r = client.post("/room/history", json={
                    "member_id": "b", "member_name": "Binh",
                    "mode": "text", "query": "người đàn ông cầm ô", "result_count": 42,
                })
                assert r.status_code == 200, r.text
                h = drain(wa, 1)[0]
                check("history broadcast", h["type"] == "history_add" and h["entry"]["member_name"] == "Binh")

                print("\n[6b] Nạp gói đề + số event TRAKE đi được tới server")
                # Regression: ba op này từng thiếu trong OpType (models/room_schemas.py)
                # -> POST trả 422 và roomClient lặng lẽ bỏ, nên đề chỉ nằm trên máy
                # người bấm rồi mất khi server phát snapshot về.
                res = op(client, "a", "An", {
                    "type": "import_package",
                    "items": [{"qid": 4, "taskType": "trake", "queryId": "query-4-trake",
                               "queryText": "1. chạy đà\n2. bật nhảy", "numEvents": 2}],
                })
                check("import_package được áp dụng", res["applied"] is True, str(res))
                drain(wa, 1)
                res = op(client, "a", "An", {"type": "set_num_events", "qid": 4, "value": 4})
                check("set_num_events được áp dụng", res["applied"] is True, str(res))
                drain(wa, 1)
                res = op(client, "a", "An", {"type": "set_query_text", "qid": 4, "value": "đề mới"})
                check("set_query_text được áp dụng", res["applied"] is True, str(res))
                drain(wa, 1)

                # Tên BTC phát phải sống sót qua việc đổi task.
                op(client, "a", "An", {"type": "set_task_type", "qid": 4, "value": "kis"})
                m = drain(wa, 1)[0]
                check("queryId của gói BTC không bị đổi tên theo task",
                      m["question"]["queryId"] == "query-4-trake", json.dumps(m["question"]))

                # Gõ tay tên có tiền tố đợt (câu 9, không đụng cấu hình câu 4 mà
                # các bước sau còn kiểm) -> hết khoá, tên tự đổi theo task nhưng
                # "p1" phải còn. Đối chiếu với test cùng tên bên
                # frontend/src/utils/submissionFormat.test.mjs.
                op(client, "a", "An", {"type": "set_query_id", "qid": 9, "value": "query-p1-9-kis"})
                drain(wa, 1)
                op(client, "a", "An", {"type": "set_task_type", "qid": 9, "value": "qa"})
                m = drain(wa, 1)[0]
                check("đổi task giữ nguyên tiền tố đợt",
                      m["question"]["queryId"] == "query-p1-9-qa", json.dumps(m["question"]))

                print("\n[6c] Nhật ký nộp dùng chung cho cả phòng")
                entry = {"member_id": "b", "member_name": "Binh", "id": "sub-1",
                         "at": "2026-08-20T10:00:00.000Z", "package_name": "goi1",
                         "zip_name": "goi1.zip", "files": [{"filename": "query-1-kis.csv", "rows": 12}]}
                r = client.post("/room/submitlog", json=entry)
                assert r.status_code == 200, r.text
                s = drain(wa, 1)[0]
                check("submitlog broadcast", s["type"] == "submitlog_add" and s["entry"]["zipName"] == "goi1.zip",
                      json.dumps(s))
                r2 = client.post("/room/submitlog", json=entry)
                check("gửi lại cùng id -> không cộng thêm lượt", r2.json()["applied"] is False, r2.text)

                # "Tạo đề mới" bên FE: vòng mới = gói mới nên bộ đếm 3 lượt phải
                # về 0 trên MỌI máy, không riêng máy bấm.
                r3 = client.post("/room/submitlog/clear")
                assert r3.status_code == 200, r3.text
                c = drain(wa, 1)[0]
                check("xoá nhật ký nộp -> broadcast submitlog_clear", c["type"] == "submitlog_clear", json.dumps(c))
                check("nhật ký nộp đã sạch",
                      client.get("/room/state").json().get("submitLog") == [],
                      json.dumps(client.get("/room/state").json().get("submitLog")))
                check("xoá lần nữa khi đã sạch -> không phát thừa",
                      client.post("/room/submitlog/clear").json()["applied"] is False)
                # Nạp lại một lượt để bước kiểm tra "còn sau restart" bên dưới
                # vẫn có cái để đếm.
                client.post("/room/submitlog", json={**entry, "id": "sub-2"})
                drain(wa, 1)

                print("\n[6d] Lịch sử tra cứu Agent - RIÊNG từng người, có kèm frame")
                # Mục đích của cả tính năng: mở lại cuộc cũ và đổ frame vào lưới
                # mà KHÔNG chạm /agent/chat, tức không tốn lượt LLM nào. Nên chỗ
                # phải kiểm là frame còn nguyên sau khi đi vòng qua server, và
                # người này không thấy lịch sử của người kia.
                def turn(tid, question, n_results=3):
                    return {
                        "id": tid, "ts": 1_700_000_000_000 + int(tid[1:]), "mode": "search",
                        "question": question, "reply": "ok",
                        "plan": {"query": question, "mode": "kis"},
                        "result_type": "grid",
                        # `duplicates` phải bị bỏ lúc lưu: nó nhân đôi payload mà
                        # xem lại thì lưới chỉ hiện đại diện.
                        "results": [{"id": f"L01_V001_{i}", "score": 0.9 - i / 10,
                                     "duplicates": [{"id": "dup"}]} for i in range(n_results)],
                    }

                def send_turn(member, chat_id, t, title="cảnh chợ nổi"):
                    r = client.post("/room/agent_chats/turn", json={
                        "member_id": member, "member_name": member.upper(),
                        "chat_id": chat_id, "title": title, "turn": t,
                    })
                    assert r.status_code == 200, r.text
                    return r.json()

                res = send_turn("a", "chat-1", turn("t1", "chợ nổi ban đêm"))
                check("lưu lượt đầu -> tạo cuộc", res["applied"] is True, json.dumps(res))
                check("gửi lại cùng turn.id -> không nhân đôi",
                      send_turn("a", "chat-1", turn("t1", "chợ nổi ban đêm"))["applied"] is False)
                send_turn("a", "chat-1", turn("t2", "thêm thuyền hoa"))

                chats = client.get("/room/agent_chats", params={"member_id": "a"}).json()["chats"]
                check("danh sách có 1 cuộc, 2 lượt",
                      len(chats) == 1 and chats[0]["turn_count"] == 2, json.dumps(chats))
                check("danh sách KHÔNG kèm frame (payload nặng)",
                      "turns" not in chats[0] and "results" not in chats[0], json.dumps(chats[0]))

                full = client.get("/room/agent_chats/chat-1", params={"member_id": "a"}).json()
                t1 = full["turns"][0]
                check("mở cuộc thì frame còn nguyên -> xem lại không cần tra lại",
                      [r["id"] for r in t1["results"]] == ["L01_V001_0", "L01_V001_1"],
                      json.dumps(t1["results"]))
                check("bỏ duplicates khi lưu", all("duplicates" not in r for r in t1["results"]))
                check("giữ plan để UI dựng lại chips", t1["plan"]["query"] == "chợ nổi ban đêm")

                check("lịch sử là RIÊNG: b không thấy cuộc của a",
                      client.get("/room/agent_chats", params={"member_id": "b"}).json()["chats"] == [])
                check("mở nhầm cuộc của người khác -> 404",
                      client.get("/room/agent_chats/chat-1", params={"member_id": "b"}).status_code == 404)

                # Trần payload: chỉ 2 lượt mới nhất còn frame (payload_turns=2 ở
                # build_app). Lượt cũ giữ phần CHỮ + cờ trimmed để UI nói thẳng
                # là phải chạy lại, thay vì hiện một nút xem lại rỗng.
                send_turn("a", "chat-1", turn("t3", "cận cảnh trái cây"))
                full = client.get("/room/agent_chats/chat-1", params={"member_id": "a"}).json()
                check("lượt cũ bị dọn frame nhưng còn chữ",
                      full["turns"][0]["trimmed"] is True
                      and full["turns"][0]["results"] == []
                      and full["turns"][0]["question"] == "chợ nổi ban đêm",
                      json.dumps(full["turns"][0]))
                check("lượt mới nhất vẫn còn frame", full["turns"][-1]["results"] != [])

                # Trần số cuộc = 2: cuộc thứ ba đẩy cuộc cũ nhất ra.
                send_turn("a", "chat-2", turn("t4", "xe máy chở hoa"), title="xe máy")
                send_turn("a", "chat-3", turn("t5", "bảng hiệu chữ vàng"), title="bảng hiệu")
                ids = [c["id"] for c in client.get("/room/agent_chats", params={"member_id": "a"}).json()["chats"]]
                check("quá trần -> cuộc cũ nhất bị cắt, mới nhất lên đầu",
                      ids == ["chat-3", "chat-2"], str(ids))

                r = client.post("/room/agent_chats/delete",
                                json={"member_id": "a", "chat_id": "chat-2"})
                check("xoá một cuộc", r.json()["applied"] is True, r.text)
                check("xoá lại cuộc đã xoá -> applied=False",
                      client.post("/room/agent_chats/delete",
                                  json={"member_id": "a", "chat_id": "chat-2"}).json()["applied"] is False)

                print("\n[7] Presence")
                wa.send_json({"type": "presence", "current": 7})
                found = False
                for _ in range(6):
                    msg = wa.receive_json()
                    if msg.get("type") == "presence":
                        an = next((m for m in msg["members"] if m["id"] == "a"), None)
                        if an and an["current"] == 7:
                            found = True
                            break
                check("presence báo đang làm câu 7", found)

            state = client.get("/room/state").json()
            expected_ids = ["f1", "f2", "f3", "f5", "f4", "f0"]
            got = [it["id"] for it in state["questions"]["3"]["items"]]
            check("GET /room/state khớp", got == expected_ids, str(got))

        print("\n[8] Restart backend -> giỏ còn nguyên")
        app2, room_mod2 = build_app(tmp)
        with TestClient(app2) as client2:
            state2 = client2.get("/room/state").json()
            got2 = [it["id"] for it in state2.get("questions", {}).get("3", {}).get("items", [])]
            check("snapshot nạp lại đủ 6 frame", got2 == expected_ids, str(got2))
            check("lịch sử còn", len(state2.get("history", [])) == 1, json.dumps(state2.get("history")))
            check("nhật ký nộp còn", len(state2.get("submitLog", [])) == 1, json.dumps(state2.get("submitLog")))

            chats2 = client2.get("/room/agent_chats", params={"member_id": "a"}).json()["chats"]
            check("lịch sử Agent còn sau restart",
                  [c["id"] for c in chats2] == ["chat-3"], json.dumps(chats2))
            full2 = client2.get("/room/agent_chats/chat-3", params={"member_id": "a"}).json()
            check("frame của lượt cuối còn sau restart -> vẫn xem lại được",
                  full2["turns"][-1]["results"][0]["id"] == "L01_V001_0", json.dumps(full2["turns"][-1]))
            q4 = state2.get("questions", {}).get("4", {})
            check("cấu hình gói đề còn nguyên sau restart",
                  q4.get("queryId") == "query-4-trake" and q4.get("numEvents") == 4
                  and q4.get("queryIdLocked") is True, json.dumps(q4))

    print("\n[8b] Nhập lại gói đề từ đầu -> xoá sạch đề vòng trước")
    # Phòng riêng: mục này cố tình xoá sạch giỏ nên không dùng chung state với
    # các mục trên được.
    #
    # Regression: `reset` không khai trong models/room_schemas.py thì pydantic
    # lặng lẽ bỏ trường -> server chạy chế độ GỘP trong khi máy bấm đã xoá sạch
    # tại chỗ, và snapshot phát về dựng lại đúng cái đề vừa bỏ.
    with tempfile.TemporaryDirectory() as td:
        app3, _ = build_app(Path(td))
        with TestClient(app3) as client3:
            with client3.websocket_connect("/room/ws?member_id=a&member_name=An") as wc:
                wc.receive_json()  # snapshot lúc connect
                op(client3, "a", "An", {"type": "import_package", "items": [
                    {"qid": 1, "taskType": "kis", "queryId": "query-1-kis"},
                    {"qid": 6, "taskType": "qa", "queryId": "query-6-qa"},
                ]})
                drain(wc, 1)
                op(client3, "a", "An", {"type": "add", "qid": 6, "item": item("cu")})
                drain(wc, 1)
                # Hạ "Số câu" KHÔNG xoá câu 6 khỏi state, nó chỉ bị ẩn - nên đây
                # đúng là cái bẫy mà reset phải dọn.
                op(client3, "a", "An", {"type": "set_num_questions", "value": 2})
                drain(wc, 1)

                res = op(client3, "a", "An", {
                    "type": "import_package", "reset": True,
                    "items": [{"qid": 1, "taskType": "qa", "queryId": "query-1-qa",
                               "queryText": "đề vòng 2"}],
                })
                check("import_package reset được áp dụng", res["applied"] is True, str(res))
                st = drain(wc, 1)[0]["state"]
                qs = st["questions"]
                check("chỉ còn đúng các câu của gói mới", sorted(qs) == ["1"], str(sorted(qs)))
                check("đáp án vòng trước bị xoá", not qs["1"]["items"], json.dumps(qs["1"]))
                check("số câu bám gói mới, không giữ số cũ", st["numQuestions"] == 1, str(st["numQuestions"]))
                check("cấu hình gói mới được nạp",
                      qs["1"]["queryId"] == "query-1-qa" and qs["1"]["queryText"] == "đề vòng 2",
                      json.dumps(qs["1"]))

                # Không có cờ reset thì vẫn phải là chế độ gộp như cũ.
                op(client3, "a", "An", {"type": "add", "qid": 1, "item": item("moi")})
                drain(wc, 1)
                op(client3, "a", "An", {
                    "type": "import_package",
                    "items": [{"qid": 1, "taskType": "trake", "queryId": "query-1-trake"}],
                })
                q1 = drain(wc, 1)[0]["state"]["questions"]["1"]
                check("gộp (không reset) giữ nguyên đáp án đã tìm",
                      [it["id"] for it in q1["items"]] == ["moi"], json.dumps(q1))

    print("\n[9] Presence gộp nhiều tab -> ổn định bất kể thứ tự duyệt")
    # RoomHub._conns là set: thứ tự lặp tuỳ ý. Nếu phép gộp phụ thuộc thứ tự thì
    # ô "đang làm câu mấy" của người mở nhiều tab sẽ nhảy qua nhảy lại giữa các
    # lần broadcast. Duyệt hết mọi thứ tự chèn và đòi ra đúng MỘT kết quả.
    from services.room_hub import Connection, RoomHub

    def conn(mid, name, current, since):
        c = Connection(None, mid, name)  # ws không dùng tới trong presence()
        c.current = current
        c.online_since = since
        return c

    # An mở 3 tab (câu 2, 7, 5), vào phòng lúc 100; Bình 1 tab câu 4, vào lúc 50.
    tabs = [("a", "An", 2, 100), ("a", "An", 7, 140), ("a", "An", 5, 120), ("b", "Binh", 4, 50)]
    seen = set()
    for perm in itertools.permutations(tabs):
        hub = RoomHub()
        for t in perm:
            hub._conns.add(conn(*t))
        seen.add(json.dumps(hub.presence(), sort_keys=True, ensure_ascii=False))
    check("mọi thứ tự chèn ra cùng một presence", len(seen) == 1, f"{len(seen)} kết quả khác nhau")

    members = json.loads(next(iter(seen)))
    an = next((m for m in members if m["id"] == "a"), None)
    check("current = câu lớn nhất trong các tab", an is not None and an["current"] == 7, str(an))
    check("online_since = lần nối sớm nhất", an is not None and an["online_since"] == 100, str(an))
    check("xếp theo online_since", [m["id"] for m in members] == ["b", "a"], str([m["id"] for m in members]))

    # --- 10. Đúng MỘT tiến trình được sở hữu file state ----------------------
    print("\n[10] Hai tiến trình không được cùng ghi một file state")
    import os  # noqa: PLC0415 - chỉ mục này cần, khỏi bắt cả file trả giá
    import subprocess  # noqa: PLC0415

    from services import room_lock  # noqa: PLC0415

    # ignore_cleanup_errors: room_lock giữ fd tới lúc tiến trình chết - đó là cả
    # điểm của nó, nên Windows không cho xoá file .lock ở đây. Bỏ lại một file
    # rỗng trong %TEMP% rẻ hơn nhiều so với việc mở một hàm release() công khai
    # mà ai đó sẽ gọi nhầm trong lúc chạy thật.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        state = Path(td) / "room-default.json"
        check("tiến trình đầu giành được khoá", room_lock.acquire(state, "smoke A") is None)

        # Phải là TIẾN TRÌNH khác, không phải lần gọi thứ hai: khoá của HĐH luôn
        # cho chính chủ lấy lại, nên gọi lại trong process này sẽ 'thành công' và
        # kiểm tra thành ra vô nghĩa.
        code = (
            "import sys;sys.path.insert(0,%r);"
            "from pathlib import Path;from services import room_lock;"
            "print(room_lock.acquire(Path(%r),'smoke B') or '')"
            % (str(Path(__file__).resolve().parent.parent), str(state))
        )
        # PYTHONIOENCODING: tiến trình con không chạy qua entry point nào nên
        # không có cú reconfigure() ở đầu file này - mà thứ nó phải in ra lại là
        # câu tiếng Việt có dấu, tức nó sẽ chết vì cp1252 đúng lúc khoá hoạt động
        # ĐÚNG, và test đọc ra thành "không có khoá".
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        out = proc.stdout.strip()
        check("tiến trình con chạy được", proc.returncode == 0, proc.stderr[-200:])
        check("tiến trình thứ hai bị từ chối", bool(out), "acquire() trả None -> hai bên cùng ghi")
        check("báo rõ ai đang giữ", "smoke A" in out and "PID" in out, out[:120])

    print()
    if failures:
        print(f"THẤT BẠI: {len(failures)} kiểm tra -> {', '.join(failures)}")
        return 1
    print("TẤT CẢ ĐỀU PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
