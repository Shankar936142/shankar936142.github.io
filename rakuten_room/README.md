# 楽天ROOM 投稿キュー

30代女性（ゆる美容×健康）向けの楽天ROOMを運用するための補助ツールです。
毎朝、売れやすい商品を選んで紹介文の下書きまで作っておくので、
人がやるのは **コピー → 「ROOMに投稿」を開く → 貼り付けて手直し → 投稿** だけになります。

## 自動化する範囲

| 作業 | 自動 | 理由 |
| --- | --- | --- |
| 商品探し（キーワード検索・レビュー★4.3以上・100件以上で絞り込み） | ✅ | 楽天公式APIを使用 |
| 季節テーマの切り替え（月ごと） | ✅ | `config.json` の `seasonal` |
| 投稿済み商品の除外 | ✅ | `data/seen.txt` |
| 紹介文の下書き（テンプレート） | ✅ | 「推しポイント」「注意」は人が直す |
| ROOMへの投稿・いいね・フォロー | ❌ | ROOMの規約で自動操作が禁止されている可能性が高く、アカウント停止のリスクがあるため |

## 準備

1. [楽天ウェブサービス](https://webservice.rakuten.co.jp/) でアプリIDを無料で発行する
   - アクセスキーも発行される場合は、それも控えておく
   - 「許可されたWebサイト」には `miyamoto477-dev.github.io` を1行だけ入れる
     （別のドメインにした場合は、Actions の Variables に `RAKUTEN_REFERER` として `https://そのドメイン/` を登録）
2. GitHub のリポジトリ → Settings → Secrets and variables → Actions で以下を登録する
   - `RAKUTEN_APP_ID`（必須）
   - `RAKUTEN_ACCESS_KEY`（必須。2026年の刷新以降の楽天APIでは必要）
   - APIのURLが変わった場合は、Variables に `RAKUTEN_API_URL` を登録する
3. このブランチを main にマージする（スケジュール実行は既定ブランチでしか動きません）

すると毎朝 6:47 に（遅れた・飛ばされたときは 8:13 と 11:41 の予備で） `rakuten_room/output/日付.md` と `.csv` がコミットされます。
GitHub のスマホアプリで `.md` を開けば、そのまま投稿作業に使えます。
Actions タブの「Run workflow」からいつでも手動で実行できます。

## ボタン付きページ（スマホ用）

毎朝、投稿リストから `https://miyamoto477-dev.github.io/room/` にボタン付きのページを公開します。
商品ごとに紹介文をその場で直せて、「コピー＆ROOMへ」で紹介文のコピーとROOMの投稿画面を開くのが1回でできます。
「済にする」で投稿済みの印を付けられます（印はそのスマホのブラウザにだけ残ります）。

ROOMへの入力・投稿はしません（規約上の自動操作にあたるため）。貼り付けと投稿ボタンは人が押します。

このリポジトリ自体が GitHub Pages で公開されているので、毎朝の実行で `room/` を更新してコミットするだけで公開されます（トークン不要）。
公開されるのは商品名・価格・紹介文の下書きだけです。

## 紹介文だけ作り直す

Actions の「Run workflow」を（作り直しのチェックなしで）押すと、その日の商品はそのままで、
楽天から商品情報を取り直して紹介文を今の書き方で作り直し、ページも更新します。

## 手元で動かす

```bash
RAKUTEN_APP_ID=xxxx python3 rakuten_room/room_queue.py
```

```bash
python3 rakuten_room/page.py   # output/*.csv から site/ にページを作る
```

```bash
python3 -m unittest discover -s rakuten_room/tests
```

## 調整

`config.json` を編集します。

- `per_day`：1日に作る件数
- `filters`：レビュー評価・件数・価格帯の条件
- `collections`：コレクション名、想定読者（「こんな人に」になる）、検索キーワード、注意書き（`note`、投稿リストに⚠で出る）
- `seasonal`：月ごとの季節キーワード
