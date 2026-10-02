"""문의 배지·이미지 정리, 시즌 아이템별, AI 판매 집계의 상품 뷰 사용, 세일 비중 높은 매장, 같은 아이템 비교, AI 도구 사용 현황. DB 는 가짜."""
from datetime import datetime

import pytest

from app import chat_tools_sale as cs
from app import feedback as fb
from app import sale_dashboard as sd
from app import sale_mix
from app import sale_products as sp
from app import sale_season as ss

M = 1_000_000


@pytest.fixture
def local_fb(temp_store, monkeypatch):
    monkeypatch.setattr(fb, "use_oracle", lambda: False)
    prefs = {}
    from app import appdb

    monkeypatch.setattr(appdb, "pref_get", lambda u, k: prefs.get((u, k)))
    monkeypatch.setattr(appdb, "pref_set", lambda u, k, v: prefs.__setitem__((u, k), v))
    return prefs


def test_feedback_badge_new_answers_and_open(local_fb, monkeypatch):
    user, admin = {"id": "u1", "name": "가", "role": "USER"}, {"id": "a1", "name": "관리", "role": "ADMIN"}
    f1 = fb.create(user, {"type": "BUG", "content": "첫 번째"})
    fb.create(user, {"type": "ASK", "content": "두 번째"})
    assert fb.badge(user) == {"newAnswers": 0, "open": None}
    assert fb.badge(admin)["open"] == 2
    monkeypatch.setattr(fb, "_now", lambda: "20261003090000")
    fb.answer(admin, f1["id"], {"status": "DONE", "answer": "고쳤습니다"})
    assert fb.badge(user)["newAnswers"] == 1 and fb.badge(admin)["open"] == 1
    monkeypatch.setattr(fb, "_now", lambda: "20261003100000")
    fb.mark_seen("u1")  # '내 문의'를 열면
    assert fb.badge(user)["newAnswers"] == 0


def test_feedback_purge_images_only_old_done(local_fb, monkeypatch):
    import base64

    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10).decode()
    user = {"id": "u1", "name": "가", "role": "USER"}
    monkeypatch.setattr(fb, "_now", lambda: "20250101090000")
    old_done = fb.create(user, {"type": "BUG", "content": "오래된 완료", "images": [{"data": png}]})
    fb.answer({"id": "a"}, old_done["id"], {"status": "DONE"})
    old_open = fb.create(user, {"type": "BUG", "content": "오래된 미완료", "images": [{"data": png}]})
    monkeypatch.setattr(fb, "_now", lambda: "20260901090000")
    new_done = fb.create(user, {"type": "BUG", "content": "최근 완료", "images": [{"data": png}]})
    fb.answer({"id": "a"}, new_done["id"], {"status": "DONE"})
    assert fb.purge_images(0) == {"deleted": 0, "bytes": 0}
    r = fb.purge_images(12, now=datetime(2026, 10, 3))
    assert r["deleted"] == 1
    assert fb.get(old_done["id"])["files"] == [] and fb.get(old_done["id"])["content"] == "오래된 완료"  # 글은 남김
    assert len(fb.get(old_open["id"])["files"]) == 1 and len(fb.get(new_done["id"])["files"]) == 1
    assert fb.image_stats()["count"] == 2


@pytest.fixture
def months(monkeypatch):
    monkeypatch.setattr(sd, "available_months", lambda: ["202609", "202608"])
    monkeypatch.setattr(sd, "brand_teams", lambda: {"리스트": ["리스트1팀"], "쉬즈미스": ["쉬즈1팀"]})
    monkeypatch.setattr(sp, "mv_state", lambda: {"exists": True, "usable": True, "mv_max": "202609", "staleness": "FRESH"})
    ss.clear_cache()
    sale_mix.clear_cache()
    yield
    ss.clear_cache()
    sale_mix.clear_cache()


def test_season_items(months, monkeypatch):
    season_rows = [("2026", "가을", "202608", 40 * M, 4, 0), ("2026", "가을", "202609", 60 * M, 6, 0),
                   ("2025", "가을", "202508", 50 * M, 5, 0), ("2025", "가을", "202510", 50 * M, 5, 0)]
    item_rows = [("2026", "자켓", "202608", 30 * M, 3), ("2026", "자켓", "202609", 40 * M, 4), ("2026", "팬츠", "202609", 30 * M, 3),
                 ("2025", "자켓", "202508", 20 * M, 2), ("2025", "자켓", "202510", 40 * M, 4), ("2025", "팬츠", "202508", 30 * M, 3),
                 ("2025", "팬츠", "202510", 10 * M, 1)]
    seen = []

    def query(sql, params=None):
        seen.append((sql, params))
        return [], (item_rows if "ITEM_NM" in sql else season_rows)
    monkeypatch.setattr(ss.db, "query", query)
    d = ss.items()
    by = {i["name"]: i for i in d["items"]}
    assert sum(i["amt"] for i in d["items"]) == d["kpi"]["amt"] == 100 * M
    assert (by["자켓"]["amt"], by["자켓"]["prevSameAmt"], by["자켓"]["prevFinalAmt"]) == (70 * M, 20 * M, 60 * M)
    assert by["자켓"]["change"] == 250.0 and by["자켓"]["progress"] == 116.7 and by["팬츠"]["share"] == 30.0
    assert sp.MV_NAME in seen[-1][0] and seen[-1][1]["py"] == "2025"


def test_aggregate_sales_uses_product_view_when_possible(monkeypatch):
    seen = []
    monkeypatch.setattr(sp, "mv_state", lambda: {"exists": True, "usable": True, "mv_max": "202609", "staleness": "FRESH"})
    monkeypatch.setattr(cs.db, "query_dicts", lambda sql, p=None: seen.append((sql, p)) or [])
    monkeypatch.setattr(cs.sm, "brand_filter", lambda *a: ([], {}))
    out = cs.run("aggregate_sales", {"ym_from": "202601", "ym_to": "202609", "group_by": ["SESS_NM"], "seasons": ["가을"],
                                     "metrics": ["REAL_SALE_AMT_SUM"]}, teams=["리스트1팀"])
    sql, p = seen[-1]
    assert sp.MV_NAME in sql and "SUM(TOTAL_SALE_AMT)" in sql and "SUBSTRB" not in sql and "TEAM_CD IN" in sql
    assert out["result"]["source"].startswith("상품 사전 집계 뷰") and "리스트1팀" in p.values()
    # 매장 조건이 있거나, 뷰에 없는 지표(매장 수)·열(수수료구분)이면 원본
    for inp in ({"shop_ids": ["S1"]}, {"metrics": ["SHOP_CNT"]}, {"charge_clsby_nm": "A"}, {"group_by": ["SHOP_ID"]}):
        base = {"ym_from": "202601", "ym_to": "202609", "group_by": ["SESS_NM"], "metrics": ["REAL_SALE_AMT_SUM"], **inp}
        cs.run("aggregate_sales", base)
        assert "T_CLOSE_SALE_BASE" in seen[-1][0], inp
    # 기간이 뷰보다 새로우면 원본
    cs.run("aggregate_sales", {"ym_from": "202609", "ym_to": "202610", "group_by": ["ITEM_NM"]})
    assert "T_CLOSE_SALE_BASE" in seen[-1][0]


def test_sale_heavy_shops(months, monkeypatch):
    # (월, 매장, 팀, 판매형태, 금액)
    rows = [("202609", "A", "리스트1팀", "세일", 30 * M), ("202609", "A", "리스트1팀", "정상", 10 * M),
            ("202609", "B", "리스트1팀", "세일", 5 * M), ("202609", "B", "리스트1팀", "행사", 35 * M),
            ("202609", "C", "리스트1팀", "세일", 20 * M),
            ("202609", "D", "리스트1팀", "세일", 1 * M),   # 월평균 1천만원 미만
            ("202509", "A", "리스트1팀", "세일", 10 * M), ("202509", "A", "리스트1팀", "정상", 30 * M)]
    monkeypatch.setattr(sale_mix.db, "query", lambda sql, p=None: ([], rows))
    monkeypatch.setattr(sale_mix.sm, "shop_names", lambda ids: {"A": "매장A", "B": "매장B", "C": "(행)매장C", "D": "매장D"})
    d = sale_mix.heavy_shops()
    assert d["brandAverages"][0]["share"] == 55.4   # 세일 56 / 전체 101 (행사는 세일 아님)
    assert [s["shopId"] for s in d["shops"]] == ["A", "B"] and d["eventShops"] == 1
    a = d["shops"][0]
    assert (a["share"], a["diff"], a["baseShare"], a["shareChange"]) == (75.0, 19.6, 25.0, 50.0)
    assert [s["shopId"] for s in sale_mix.heavy_shops(include_event=True)["shops"]][0] == "C"


def test_product_siblings_same_brand(monkeypatch):
    monkeypatch.setattr(sp, "mv_state", lambda: {"exists": True, "usable": True, "mv_max": "202609", "staleness": "FRESH"})
    monkeypatch.setattr(sd, "brand_teams", lambda: {"리스트": ["리스트1팀", "리스트2팀"], "쉬즈미스": ["쉬즈1팀"]})
    seen = []

    def query(sql, params=None):
        seen.append((sql, params))
        if "GROUP BY PLAN_YY" in sql:
            return [], [("2026", "가을", "자켓", "리스트2팀", 100)]
        return [], [("P1", "우븐", 50, 5 * M, 0, "202607", "202609"), ("ME", "우븐", 80, 8 * M, 0, "202607", "202609"),
                    ("P3", "우븐", 20, 2 * M, 0, "202608", "202609")]
    monkeypatch.setattr(sp.db, "query", query)
    d = sp.product_siblings("ME", top=1)
    assert (d["brand"], d["count"], d["rank"], d["avgQty"]) == ("리스트", 3, 1, 50)
    assert sorted(v for k, v in seen[-1][1].items() if k.startswith("t")) == ["리스트1팀", "리스트2팀"]  # 같은 브랜드만
    assert [r["prdtCd"] for r in d["rows"]] == ["ME"]
    assert sp.product_siblings("ME", top=1, teams=["쉬즈1팀"]) is not None
    monkeypatch.setattr(sp, "mv_state", lambda: {"exists": False, "usable": False, "mv_max": None, "staleness": None})
    assert sp.product_siblings("ME") is None


def test_ai_tool_stats_from_log(tmp_path, monkeypatch):
    from app import ai_tool_stats, logs

    log = tmp_path / "app.log"
    today = datetime.now().strftime("%Y-%m-%d")
    log.write_text("\n".join([
        f"{today} 09:00:00 INFO  erp.ai       질문 user=u1 conv=c1 model=claude-haiku-4-5 effort=low route=simple view=x len=10",
        f"{today} 09:00:01 INFO  erp.ai       도구 aggregate_sales user=u1 2.5s 입력={{}}",
        f"{today} 09:00:02 INFO  erp.ai       도구 입력 오류 aggregate_sales user=u1: ym_from 은 202601 형식",
        f"{today} 09:00:03 INFO  erp.ai       도구 입력 오류 aggregate_sales user=u2: ym_from 은 202602 형식",
        f"{today} 09:00:04 ERROR erp.ai       도구 실패 search_sales user=u2 입력={{}}",
        f"{today} 09:00:05 INFO  erp.ai       모델 전환 user=u1 conv=c1 claude-haiku-4-5 → claude-opus-5 (도구 입력 오류 2회)",
        f"{today} 09:00:06 INFO  erp.ai       도구 aggregate_sales user=u2 0.5s 입력={{}}",
        f"{today} 09:00:07 INFO  erp.request  user=u1 GET /api/x 200 5ms",
    ]) + "\n", encoding="utf-8")
    monkeypatch.setattr(logs, "app_log_files", lambda days: [log])
    d = ai_tool_stats.report(7)
    assert (d["questions"], d["routes"], d["modelSwitches"]) == (1, {"simple": 1}, 1)
    agg = next(t for t in d["tools"] if t["name"] == "aggregate_sales")
    assert (agg["calls"], agg["ok"], agg["inputErrors"], agg["users"], agg["avgSec"], agg["maxSec"]) == (4, 2, 2, 2, 1.5, 2.5)
    assert agg["errorRate"] == 50.0 and agg["topErrors"] == [{"message": "ym_from 은 N 형식", "count": 2}]
    ss_ = next(t for t in d["tools"] if t["name"] == "search_sales")
    assert ss_["failures"] == 1 and ss_["avgSec"] is None
    assert "get_season_progress" in [u["name"] for u in d["unusedTools"]]
