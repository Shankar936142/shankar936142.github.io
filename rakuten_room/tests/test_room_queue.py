import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import room_queue as rq  # noqa: E402

CONFIG = json.loads((Path(__file__).resolve().parents[1] / "config.json").read_text(encoding="utf-8"))


def item(code, avg=4.5, cnt=1000, price=2000, point=1, name=None):
    return {"itemCode": code, "itemName": name if name is not None else f"商品{code}", "itemPrice": price, "reviewAverage": avg,
            "reviewCount": cnt, "pointRate": point, "shopName": "shop", "itemUrl": f"https://x/{code}",
            "catchcopy": "ワンタッチで時短"}


class QueueTest(unittest.TestCase):
    def test_filters(self):
        f = CONFIG["filters"]
        self.assertTrue(rq.passes(item("a"), f))
        self.assertFalse(rq.passes(item("b", avg=4.0), f))
        self.assertFalse(rq.passes(item("c", cnt=10), f))
        self.assertFalse(rq.passes(item("d", price=99999), f))

    def test_build_queue_dedupes_and_limits(self):
        n = iter(range(10**6))

        def fetch(kw):
            k = next(n)
            return [item(f"s:{k}", name=kw), item("s:dup", name=kw), item(f"bad{k}", avg=3.0, name=kw)]

        seen = {"s:dup"}
        q = rq.build_queue(CONFIG, fetch, dt.date(2026, 11, 4), seen)
        self.assertEqual(len(q), CONFIG["per_day"])
        codes = [x["item_code"] for x in q]
        self.assertNotIn("s:dup", codes)
        self.assertEqual(len(codes), len(set(codes)))
        self.assertTrue(all(c in seen for c in codes))
        self.assertIn("room.rakuten.co.jp/mix?itemcode=s%3A", q[0]["room_post_url"])

    def test_fetch_error_is_skipped(self):
        def fetch(kw):
            raise OSError("network")
        self.assertEqual(rq.build_queue(CONFIG, fetch, dt.date(2026, 11, 4), set()), [])

    def test_formatversion1_and_text(self):
        self.assertEqual(rq.normalize({"Item": {"a": 1}}), {"a": 1})
        t = rq.draft_text(item("x", point=5), "忙しい人", "大掃除")
        self.assertIn("ポイント5倍", t)
        self.assertIn("★4.50（1,000件）", t)
        self.assertNotIn("こんな人に", t)

    def test_product_intro_text(self):
        it = {"itemName": "【楽天1位】＼最大20%OFF／ iwaki 耐熱ガラス 保存容器 7点セット 送料無料",
              "itemCaption": "電子レンジ・オーブンにそのまま使える耐熱ガラス製です。においや色が移りにくく、"
                             "作り置きにぴったり。※画像はイメージです。シミが消える新習慣。"
                             "送料無料でお届けします。中身が見えるので冷蔵庫の整理もしやすい",
              "reviewAverage": 4.71, "reviewCount": 2446}
        t = rq.draft_text(it)
        first = t.splitlines()[0]
        self.assertIn("iwaki 耐熱ガラス 保存容器 7点セット", first)
        for w in ("楽天1位", "OFF", "送料無料", "【"):
            self.assertNotIn(w, first)
        self.assertIn("✔ においや色が移りにくく、作り置きにぴったり", t)
        self.assertIn("✔ 中身が見えるので冷蔵庫の整理もしやすい", t)
        self.assertNotIn("シミが消える", t)   # 言い切りの表現は使わない
        self.assertNotIn("画像はイメージ", t)  # 注意書きは使わない
        self.assertIn("レビュー★4.71（2,446件）", t)

    def test_product_intro_fallback(self):
        t = rq.draft_text({"itemName": "商品", "reviewAverage": 4.5, "reviewCount": 10})
        self.assertIn("（使って良かった点・特徴を書く）", t)

    def test_write_outputs(self):
        q = rq.build_queue(CONFIG, lambda kw: [item(kw)], dt.date(2026, 12, 1), set())
        with tempfile.TemporaryDirectory() as d:
            md, cs = rq.write_outputs(q, Path(d), dt.date(2026, 12, 1))
            self.assertIn("ROOMに投稿", md.read_text(encoding="utf-8"))
            self.assertTrue(cs.read_text(encoding="utf-8-sig").startswith("collection,"))


class RealDataTest(unittest.TestCase):
    def test_keyword_must_appear_in_name(self):
        battery = item("s:1", cnt=99999, name="モバイルバッテリー 軽量")
        blanket = item("s:2", cnt=500, name="電気毛布 洗える ひざ掛け")
        cfg = dict(CONFIG, collections=[{"name": "c", "target": "t", "keywords": ["電気毛布"]}],
                   seasonal={})
        q = rq.build_queue(cfg, lambda kw: [battery, blanket], dt.date(2026, 11, 4), set())
        self.assertEqual([x["item_code"] for x in q], ["s:2"])

    def test_item_url_whitespace_removed(self):
        def fetch(kw):
            it = item("s:3", name=kw)
            it["itemUrl"] = "https://item.rakuten.co.jp/a/b/?rafcid=wsc_x\n\npk_y"
            return [it]
        q = rq.build_queue(CONFIG, fetch, dt.date(2026, 11, 4), set())
        self.assertEqual(q[0]["item_url"], "https://item.rakuten.co.jp/a/b/?rafcid=wsc_xpk_y")


class RetextTest(unittest.TestCase):
    def test_retext_keeps_items_and_rewrites_text(self):
        q = rq.build_queue(CONFIG, lambda kw: [item("s:" + kw, name=kw)], dt.date(2026, 11, 5), set())
        with tempfile.TemporaryDirectory() as d:
            rq.write_outputs(q, Path(d), dt.date(2026, 11, 5))
            rows = rq.read_csv_queue(Path(d) / "2026-11-05.csv")
            codes = [r["item_code"] for r in rows]

            def fetch_one(code):
                if code == codes[0]:
                    raise OSError("down")  # 取り直せない商品は手元の情報で作る
                return [dict(item(code, name="【楽天1位】新しい商品名"),
                             itemCaption="毎日使いやすいコンパクトなサイズです")]

            n = rq.retext_queue(rows, fetch_one, "乾燥対策")
            self.assertEqual(n, len(rows) - 1)
            self.assertEqual([r["item_code"] for r in rows], codes)  # 商品は変わらない
            self.assertTrue(all("こんな人に" not in r["text"] for r in rows))
            self.assertIn("✔ 毎日使いやすいコンパクトなサイズです", rows[1]["text"])
            self.assertTrue(rows[1]["text"].startswith("新しい商品名"))
            md, _ = rq.write_outputs(rows, Path(d), dt.date(2026, 11, 5))
            self.assertIn("✔", md.read_text(encoding="utf-8"))


class MainTest(unittest.TestCase):
    def test_empty_env_uses_default_url_and_fails_when_all_errors(self):
        import os
        from unittest import mock
        seen_urls = []

        def fake(kw, f, app_id, api_url, access_key=None, hits=30):
            seen_urls.append((api_url, access_key))
            raise OSError("boom")

        env = {"RAKUTEN_APP_ID": "x", "RAKUTEN_API_URL": "", "RAKUTEN_ACCESS_KEY": "k"}
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, env), \
                mock.patch.object(rq, "search_items", fake), mock.patch.object(rq.time, "sleep"):
            code = rq.main(["--out", d, "--seen", str(Path(d) / "seen.txt"), "--date", "2026-11-04"])
        self.assertEqual(code, 1)
        self.assertEqual(seen_urls[0], (rq.DEFAULT_API, "k"))

    def test_missing_access_key_stops(self):
        import os
        from unittest import mock
        env = {"RAKUTEN_APP_ID": "x", "RAKUTEN_API_URL": "", "RAKUTEN_ACCESS_KEY": ""}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(rq.main([]), 2)


if __name__ == "__main__":
    unittest.main()
