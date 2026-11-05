#!/usr/bin/env python3
"""楽天ROOM 投稿キュー生成ツール

楽天市場の公式API（楽天ウェブサービス）で商品を探し、
レビュー条件で絞り込んで、紹介文の下書きと「ROOMに投稿」リンクを
Markdown / CSV に書き出す。

ROOM への投稿・いいね・フォローは自動化しない（規約違反のおそれがあるため）。
最後の「投稿」ボタンは人が押す前提。

標準ライブラリのみで動く。
  RAKUTEN_APP_ID=xxxx python3 rakuten_room/room_queue.py
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
# 2026年の楽天ウェブサービス刷新後の接続先（旧 app.rakuten.co.jp は新形式のアプリIDを受け付けない）
DEFAULT_API = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701"
ROOM_POST_URL = "https://room.rakuten.co.jp/mix?itemcode={code}"


# ---------------------------------------------------------------- API
def search_items(keyword: str, filters: dict, app_id: str, api_url: str = DEFAULT_API,
                 access_key: str | None = None, hits: int = 30) -> list[dict]:
    params = {
        "applicationId": app_id,
        "keyword": keyword,
        "hits": hits,
        "sort": "-reviewCount",
        "availability": 1,
        "formatVersion": 2,
        "format": "json",
    }
    if filters.get("min_price"):
        params["minPrice"] = filters["min_price"]
    if filters.get("max_price"):
        params["maxPrice"] = filters["max_price"]
    if access_key:
        params["accessKey"] = access_key
    url = f"{api_url}?{urllib.parse.urlencode(params)}"
    headers = {"User-Agent": "room-queue/1.0"}
    referer = os.environ.get("RAKUTEN_REFERER")
    if referer:
        # 「許可されたWebサイト」に登録したドメインからのリクエストとして送る
        headers["Referer"] = referer
        headers["Origin"] = referer.rstrip("/")
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as res:
        data = json.load(res)
    return [normalize(i) for i in data.get("Items", [])]


def describe(e: Exception) -> str:
    """HTTPエラーなら楽天APIが返したメッセージも添える（原因が分かるように）。"""
    if isinstance(e, urllib.error.HTTPError):
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            body = ""
        return f"HTTP {e.code} {body}"
    return str(e)


def normalize(item: dict) -> dict:
    """formatVersion=1（{"Item": {...}}）と 2（フラット）の両方を受け付ける。"""
    return item.get("Item", item)


# ---------------------------------------------------------------- 絞り込み
def matches_keyword(item: dict, keyword: str) -> bool:
    """検索語の単語がすべて商品名に入っているか（関係ない商品が上位に混ざるのを防ぐ）。"""
    name = (item.get("itemName") or "").lower()
    return all(w.lower() in name for w in keyword.split())


def clean_url(url: str) -> str:
    # 新APIの itemUrl には改行などの空白が混ざることがあり、そのままだとリンクが切れる
    return "".join((url or "").split())


def passes(item: dict, f: dict) -> bool:
    return (
        float(item.get("reviewAverage") or 0) >= f.get("min_review_average", 0)
        and int(item.get("reviewCount") or 0) >= f.get("min_review_count", 0)
        and f.get("min_price", 0) <= int(item.get("itemPrice") or 0) <= f.get("max_price", 10**9)
    )


def score(item: dict) -> float:
    # レビュー件数（売れている証拠）と評価、ポイント倍率を合わせた簡易スコア
    import math
    return (math.log10(int(item.get("reviewCount") or 1) + 1) * float(item.get("reviewAverage") or 0)
            + 0.2 * int(item.get("pointRate") or 1))


# ---------------------------------------------------------------- 紹介文
def shorten(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


# 商品名から外す宣伝文句（【】や＼／で囲まれた部分、送料・クーポンなど）
_NAME_NOISE = re.compile(r"【[^】]*】|［[^］]*］|\[[^\]]*\]|＼[^／]*／|<[^>]*>|★|☆|◆|◇|■|□|●|○|♪|！|!")
_NAME_WORDS = re.compile(r"(送料無料|ポイント\d*倍|最大\d+%OFF|\d+%OFF|クーポン\S*|SALE|セール|楽天\d*位|ランキング\S*|あす楽|翌日配送|即納|公式|正規品|限定)")
# 特徴文として使わない文（注意書き・配送・型番など）
_SKIP = re.compile(r"(http|※|注意|送料|配送|お届け|発送|返品|交換|キャンセル|クーポン|ポイント|JAN|型番|品番|メーカー|製造|販売|原産|生産国|保証|お問い合わせ|ご了承|ご注意|画像|モニター|ランキング|レビュー|楽天|商品番号)")
# 薬機法・景表法の観点で言い切りになりやすい語を含む文は使わない
_CLAIM = re.compile(r"(治|改善|効く|効果|効能|若返|痩せ|やせ|シミが|消える|美白|解消|予防|アンチエイジング|医師|医療|No\.?1|ナンバーワン|日本一|最高|最強|絶対|完全)")


def clean_name(name: str) -> str:
    name = _NAME_NOISE.sub(" ", name or "")
    name = _NAME_WORDS.sub(" ", name)
    return shorten(name.strip(" 　/|｜・-"), 40)


def features(item: dict, n: int = 3) -> list[str]:
    """商品説明文から、短くて言い切りのない特徴文を最大 n 個取り出す。"""
    text = (item.get("itemCaption") or "") + "。" + (item.get("catchcopy") or "")
    out: list[str] = []
    for seg in re.split(r"[。\n\r！!？?]|<br\s*/?>|・|■|◆|●|★|☆|／|｜", text):
        seg = " ".join(seg.split()).strip(" 　:：-－、,")
        if not (8 <= len(seg) <= 40) or _SKIP.search(seg) or _CLAIM.search(seg):
            continue
        if seg.count(" ") >= 3:  # キーワードの羅列は文章にならないので除く
            continue
        if seg not in out:
            out.append(seg)
        if len(out) >= n:
            break
    return out


def draft_text(item: dict, target: str = "", season_label: str | None = None) -> str:
    """ROOMの商品紹介欄にそのまま貼れる、商品そのものの紹介文を作る。"""
    lines = [clean_name(item.get("itemName", ""))]
    feats = features(item)
    if feats:
        lines.append("")
        lines += [f"✔ {f}" for f in feats]
    else:
        lines += ["", "✔ （使って良かった点・特徴を書く）"]
    avg, cnt = float(item.get("reviewAverage") or 0), int(item.get("reviewCount") or 0)
    lines += ["", f"レビュー★{avg:.2f}（{cnt:,}件）の人気アイテムです。"]
    if int(item.get("pointRate") or 1) > 1:
        lines.append(f"今ならポイント{item['pointRate']}倍。")
    elif season_label:
        lines.append(f"{season_label}の時期にもぴったりです。")
    return "\n".join(lines)


def room_url(item_code: str) -> str:
    return ROOM_POST_URL.format(code=urllib.parse.quote(item_code, safe=""))


# ---------------------------------------------------------------- 本体
def build_queue(config: dict, fetch, today: dt.date, seen: set[str]) -> list[dict]:
    f = config["filters"]
    season = config.get("seasonal", {}).get(str(today.month))
    targets = [(c["name"], c["target"], kw, c.get("note", ""))
               for c in config["collections"] for kw in c["keywords"]]
    if season:
        targets += [(f"季節：{season['label']}", season.get("target", "この時期に買い替え・準備したい人"),
                     kw, season.get("note", ""))
                    for kw in season["keywords"]]

    # 毎日同じキーワードばかりにならないよう、日付で開始位置をずらす
    start = today.toordinal() % len(targets)
    targets = targets[start:] + targets[:start]

    picked: list[dict] = []
    per_day = config.get("per_day", 10)
    for coll, target, kw, note in targets:
        if len(picked) >= per_day:
            break
        try:
            items = fetch(kw)
        except Exception as e:  # 1キーワードの失敗で全体を止めない
            print(f"[warn] {kw}: {describe(e)}", file=sys.stderr)
            continue
        cands = sorted((i for i in items if passes(i, f) and matches_keyword(i, kw)
                        and i.get("itemCode") not in seen),
                       key=score, reverse=True)
        if not cands:
            continue
        it = cands[0]  # 1キーワードにつき1商品で、偏りを防ぐ
        seen.add(it["itemCode"])
        picked.append({
            "collection": coll,
            "note": note,
            "keyword": kw,
            "name": shorten(it.get("itemName", ""), 50),
            "shop": it.get("shopName", ""),
            "price": int(it.get("itemPrice") or 0),
            "review_average": float(it.get("reviewAverage") or 0),
            "review_count": int(it.get("reviewCount") or 0),
            "point_rate": int(it.get("pointRate") or 1),
            "item_code": it["itemCode"],
            "item_url": clean_url(it.get("itemUrl", "")),
            "room_post_url": room_url(it["itemCode"]),
            "text": draft_text(it, target, season["label"] if season else None),
        })
    return picked


def write_outputs(queue: list[dict], out_dir: Path, today: dt.date) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md = out_dir / f"{today.isoformat()}.md"
    cs = out_dir / f"{today.isoformat()}.csv"
    with md.open("w", encoding="utf-8") as fp:
        fp.write(f"# 楽天ROOM 投稿キュー {today.isoformat()}（{len(queue)}件）\n\n")
        fp.write("手順：紹介文をコピー → 「ROOMに投稿」を開く → 貼り付けて、（）の部分を直して投稿\n\n")
        for n, q in enumerate(queue, 1):
            fp.write(f"## {n}. {q['name']}\n\n")
            fp.write(f"- コレクション：{q['collection']}（検索語：{q['keyword']}）\n")
            if q.get("note"):
                fp.write(f"- ⚠ {q['note']}\n")
            fp.write(f"- {q['price']:,}円／★{q['review_average']:.2f}（{q['review_count']:,}件）／{q['shop']}\n")
            fp.write(f"- [商品ページ]({q['item_url']})　[ROOMに投稿]({q['room_post_url']})\n\n")
            fp.write("```\n" + q["text"] + "\n```\n\n")
    with cs.open("w", encoding="utf-8-sig", newline="") as fp:  # Excel で文字化けしないよう BOM 付き
        w = csv.DictWriter(fp, fieldnames=list(queue[0].keys()) if queue else ["collection"])
        w.writeheader()
        w.writerows(queue)
    return md, cs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="楽天ROOMの投稿キューを作る")
    p.add_argument("--config", default=str(HERE / "config.json"))
    p.add_argument("--out", default=str(HERE / "output"))
    p.add_argument("--seen", default=str(HERE / "data" / "seen.txt"),
                   help="一度キューに入れた商品コードの記録（重複防止）")
    p.add_argument("--date", help="YYYY-MM-DD（季節テーマの確認用）")
    args = p.parse_args(argv)

    app_id = os.environ.get("RAKUTEN_APP_ID")
    if not app_id:
        print("環境変数 RAKUTEN_APP_ID を設定してください（楽天ウェブサービスで無料発行）", file=sys.stderr)
        return 2
    # GitHub Actions では未設定の変数が空文字で渡ってくるので、空なら既定値にする
    api_url = os.environ.get("RAKUTEN_API_URL") or DEFAULT_API
    access_key = os.environ.get("RAKUTEN_ACCESS_KEY") or None
    if not access_key and "openapi.rakuten.co.jp" in api_url:
        print("環境変数 RAKUTEN_ACCESS_KEY を設定してください（新しい楽天APIでは必須。"
              "楽天ウェブサービスの「アプリ情報の確認」で確認できます）", file=sys.stderr)
        return 2

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    seen_path = Path(args.seen)
    seen = set(seen_path.read_text().split()) if seen_path.exists() else set()

    def fetch(kw: str) -> list[dict]:
        time.sleep(1.1)  # API の目安（1秒に1回）を守る
        return search_items(kw, config["filters"], app_id, api_url, access_key)

    errors: list[str] = []

    def fetch_logged(kw: str) -> list[dict]:
        try:
            return fetch(kw)
        except Exception as e:
            errors.append(f"{kw}: {describe(e)}")
            raise

    queue = build_queue(config, fetch_logged, today, seen)
    if not queue and errors:
        # 全キーワードが失敗したら、成功扱いにせず止める（空のリストをコミットしない）
        print("楽天APIの呼び出しがすべて失敗しました。最初のエラー:", errors[0], file=sys.stderr)
        return 1
    md, cs = write_outputs(queue, Path(args.out), today)
    seen_path.parent.mkdir(parents=True, exist_ok=True)
    seen_path.write_text("\n".join(sorted(seen)) + "\n")
    print(f"{len(queue)}件 → {md} / {cs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
