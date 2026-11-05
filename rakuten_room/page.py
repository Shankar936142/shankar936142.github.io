#!/usr/bin/env python3
"""投稿リスト（CSV）から、スマホで使うボタン付きのページ（HTML）を作る。

商品ごとに「コピーしてROOMを開く」ボタンを置く。
ボタンを押すと、紹介文（その場で編集できる）がコピーされ、ROOMの投稿画面が開く。
ROOMへの入力・投稿そのものは人が行う（自動操作はしない）。

  python3 rakuten_room/page.py              # output/*.csv → site/
  python3 rakuten_room/page.py --out DIR
"""
from __future__ import annotations

import argparse
import csv
import html
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

CSS = """
:root{--bg:#fff7f9;--card:#fff;--ink:#2b2226;--sub:#7a6a70;--line:#f0dbe2;--accent:#d6336c;--accent-ink:#fff;--done:#2f9e44;--warn:#fff3bf;--warn-ink:#6b5400}
@media (prefers-color-scheme:dark){:root{--bg:#1c1719;--card:#262022;--ink:#f3eaee;--sub:#b9a7ae;--line:#3a3034;--accent:#f06595;--accent-ink:#1c1719;--done:#69db7c;--warn:#3d3510;--warn-ink:#ffe066}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 -apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP",sans-serif}
main{max-width:640px;margin:0 auto;padding:16px}
h1{font-size:1.25rem;margin:8px 0 4px}
.lead{color:var(--sub);font-size:.9rem;margin:0 0 16px}
.progress{font-weight:700;color:var(--accent)}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin:0 0 14px}
.card.done{opacity:.6}
.num{color:var(--sub);font-size:.8rem}
.name{font-weight:700;margin:2px 0 6px;font-size:.98rem}
.meta{color:var(--sub);font-size:.82rem;margin:0 0 8px}
.meta a{color:var(--sub)}
.warn{background:var(--warn);color:var(--warn-ink);border-radius:8px;padding:6px 8px;font-size:.8rem;margin:0 0 8px}
textarea{width:100%;min-height:12em;border:1px solid var(--line);border-radius:10px;padding:10px;font:inherit;font-size:.92rem;background:transparent;color:inherit;resize:vertical}
.row{display:flex;gap:8px;margin-top:10px}
button{flex:1;border:0;border-radius:12px;padding:14px 10px;font:inherit;font-weight:700;cursor:pointer;min-height:48px}
.go{background:var(--accent);color:var(--accent-ink)}
.mark{flex:0 0 auto;background:transparent;border:1px solid var(--line);color:var(--sub);padding:14px}
.card.done .mark{color:var(--done);border-color:var(--done)}
.toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:var(--ink);color:var(--bg);padding:10px 16px;border-radius:999px;font-size:.9rem;opacity:0;transition:opacity .2s;pointer-events:none}
.toast.show{opacity:1}
nav{margin:20px 0;font-size:.85rem;color:var(--sub)}
nav a{color:var(--sub);margin-right:10px}
"""

JS = r"""
const KEY = 'room-done-' + document.body.dataset.date;
function load(){ try { return JSON.parse(localStorage.getItem(KEY) || '[]'); } catch(e){ return []; } }
function save(v){ try { localStorage.setItem(KEY, JSON.stringify(v)); } catch(e){} }
function refresh(){
  const done = load(); let n = 0;
  document.querySelectorAll('.card').forEach(c => {
    const on = done.includes(c.dataset.code); c.classList.toggle('done', on); if (on) n++;
    c.querySelector('.mark').textContent = on ? '✓ 投稿済み' : '済にする';
  });
  const p = document.querySelector('.progress'); if (p) p.textContent = n + ' / ' + document.querySelectorAll('.card').length + ' 件 投稿済み';
}
function toast(msg){ const t = document.querySelector('.toast'); t.textContent = msg; t.classList.add('show'); setTimeout(() => t.classList.remove('show'), 1800); }
async function copy(text){
  try { await navigator.clipboard.writeText(text); return true; } catch(e) {}
  const ta = document.createElement('textarea'); ta.value = text; ta.style.position='fixed'; ta.style.opacity='0';
  document.body.appendChild(ta); ta.select(); let ok = false; try { ok = document.execCommand('copy'); } catch(e) {}
  ta.remove(); return ok;
}
document.addEventListener('click', async ev => {
  const card = ev.target.closest('.card'); if (!card) return;
  if (ev.target.matches('.go')) {
    const ok = await copy(card.querySelector('textarea').value);
    toast(ok ? 'コピーしました。ROOMの紹介文欄に貼り付けてください' : 'コピーできませんでした。文章を長押ししてコピーしてください');
    if (ok) setTimeout(() => { location.href = card.dataset.room; }, 600);
  }
  if (ev.target.matches('.mark')) {
    const done = load(), i = done.indexOf(card.dataset.code);
    if (i >= 0) done.splice(i, 1); else done.push(card.dataset.code);
    save(done); refresh();
  }
});
refresh();
"""


def read_queue(csv_path: Path) -> list[dict]:
    with csv_path.open(encoding="utf-8-sig", newline="") as fp:
        return [r for r in csv.DictReader(fp) if r.get("item_code")]


def render(date: str, queue: list[dict], others: list[str]) -> str:
    e = html.escape
    cards = []
    for n, q in enumerate(queue, 1):
        warn = f'<p class="warn">⚠ {e(q["note"])}</p>' if q.get("note") else ""
        price = f'{int(float(q.get("price") or 0)):,}円'
        cards.append(f"""
<section class="card" data-code="{e(q['item_code'])}" data-room="{e(q['room_post_url'])}">
  <div class="num">{n}. {e(q.get('collection', ''))}</div>
  <div class="name">{e(q.get('name', ''))}</div>
  <p class="meta">{price}／★{float(q.get('review_average') or 0):.2f}（{int(float(q.get('review_count') or 0)):,}件）／<a href="{e(q.get('item_url', ''))}" target="_blank" rel="noopener">商品ページ</a></p>
  {warn}
  <textarea aria-label="紹介文">{e(q.get('text', ''))}</textarea>
  <div class="row"><button class="go">コピー＆ROOMへ</button><button class="mark">済にする</button></div>
</section>""")
    nav = "".join(f'<a href="{e(d)}.html">{e(d)}</a>' for d in others[:14])
    body = "".join(cards) or "<p>この日の商品はありません。</p>"
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>ROOM投稿リスト {e(date)}</title>
<style>{CSS}</style></head>
<body data-date="{e(date)}"><main>
<h1>ROOM投稿リスト {e(date)}</h1>
<p class="lead">① 紹介文の（）を直す → ②「コピー＆ROOMへ」→ ③ 紹介文欄を長押しして貼り付け → 投稿<br><span class="progress"></span></p>
{body}
<nav>過去のリスト：{nav}</nav>
</main><div class="toast" role="status"></div>
<script>{JS}</script></body></html>
"""


def build_site(src: Path, out: Path) -> list[Path]:
    csvs = sorted(src.glob("*.csv"), reverse=True)  # 新しい日付が先
    dates = [p.stem for p in csvs]
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for p in csvs:
        page = render(p.stem, read_queue(p), [d for d in dates if d != p.stem])
        dest = out / f"{p.stem}.html"
        dest.write_text(page, encoding="utf-8")
        written.append(dest)
    if csvs:  # index.html は最新の日
        (out / "index.html").write_text(written[0].read_text(encoding="utf-8"), encoding="utf-8")
        written.append(out / "index.html")
    return written


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="投稿リストのボタン付きページを作る")
    p.add_argument("--src", default=str(HERE / "output"))
    p.add_argument("--out", default=str(HERE.parent / "site"))
    args = p.parse_args(argv)
    written = build_site(Path(args.src), Path(args.out))
    print(f"{len(written)}ファイル → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
