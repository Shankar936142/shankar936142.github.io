import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import page  # noqa: E402

ROW = {"collection": "ゆる食事管理", "note": "効果を言い切らない", "keyword": "k", "name": "<b>商品</b>",
       "shop": "s", "price": "3850", "review_average": "4.71", "review_count": "2446", "point_rate": "1",
       "item_code": "shop:1", "item_url": "https://item.rakuten.co.jp/a/1/",
       "room_post_url": "https://room.rakuten.co.jp/mix?itemcode=shop%3A1", "text": "【こんな人に】<script>"}


def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


class PageTest(unittest.TestCase):
    def test_build_site(self):
        with tempfile.TemporaryDirectory() as d:
            src, out = Path(d) / "src", Path(d) / "out"
            src.mkdir()
            write_csv(src / "2026-11-04.csv", [dict(ROW, item_code="shop:0")])
            write_csv(src / "2026-11-05.csv", [ROW])
            page.build_site(src, out)
            idx = (out / "index.html").read_text(encoding="utf-8")
            self.assertIn("ROOM投稿リスト 2026-11-05", idx)  # index は最新の日
            self.assertIn('data-room="https://room.rakuten.co.jp/mix?itemcode=shop%3A1"', idx)
            self.assertIn("&lt;b&gt;商品&lt;/b&gt;", idx)  # HTML はエスケープされる
            self.assertNotIn("【こんな人に】<script>", idx)
            self.assertIn('href="2026-11-04.html"', idx)
            self.assertIn("⚠ 効果を言い切らない", idx)

    def test_old_csv_without_note(self):
        row = {k: v for k, v in ROW.items() if k != "note"}
        html = page.render("2026-11-04", [row], [])
        self.assertNotIn('class="warn"', html)


if __name__ == "__main__":
    unittest.main()
