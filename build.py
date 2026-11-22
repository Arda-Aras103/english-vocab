#!/usr/bin/env python3
"""
Normalize, deduplicate, and sort English vocabulary entries into
/workspace/notes/40-english/vocabulary.md, and generate a fast,
offline single-file Tokyo Night viewer at /workspace/apps/vocab.html.

Usage:
  python3 /workspace/scripts/build_vocab.py                 # Rebuild vocab.html from vocabulary.md
  python3 /workspace/scripts/build_vocab.py --normalize     # Deduplicate & sort vocabulary.md + rebuild HTML
  python3 /workspace/scripts/build_vocab.py --import-inbox  # Merge 00-inbox.md into vocabulary.md + rebuild HTML
"""

import argparse
import json
import re
from collections import OrderedDict
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
VOCAB_MD = WORKSPACE / "notes" / "40-english" / "vocabulary.md"
INBOX_MD = WORKSPACE / "notes" / "00-inbox.md"
VOCAB_HTML = WORKSPACE / "apps" / "vocab.html"


def clean_line(s: str) -> str:
    return s.replace("\u00a0", " ").replace("\u200b", "").strip()


def format_kv_bullet(item: str, italicize_example: bool = False) -> str:
    """Ensure '- **Key:** value' formatting cleanly."""
    item = item.strip()
    # Already bolded key?
    if item.startswith("**"):
        return f"- {item}"
    m = re.match(r"^([^:]{1,60}):\s*(.+)$", item)
    if m:
        key, val = m.group(1).strip(), m.group(2).strip()
        if italicize_example and "(*" not in val:
            # Italicize inline parenthetical example like (foo bar — baz)
            val = re.sub(
                r"\(([A-Za-z][^()—–-]{1,60}?)\s+[—–-]\s+([^()]+)\)",
                r"(*\1* — \2)",
                val,
            )
        return f"- **{key}:** {val}"
    return f"- {item}"


def parse_block(word: str, block: list[str]) -> dict:
    okunus = ""
    tur = ""
    anlamlar = []
    kaliplar = []
    ornekler = []

    section = "meta"
    for l in block:
        if re.match(r"^[-─━*]+$", l) or l.startswith("# "):
            continue
        if re.match(r"^(?:###\s+)?Anlamlar$", l):
            section = "anlamlar"
            continue
        if re.match(r"^(?:###\s+)?Kalıplar$", l):
            section = "kaliplar"
            continue
        if re.match(r"^(?:###\s+)?Örnek(?:ler)?$", l):
            section = "ornek"
            continue

        if section == "meta":
            m_ok = re.match(r"^[•\-*]\s*(?:\*\*)?Okunuş:(?:\*\*)?\s*(.+)$", l)
            m_tur = re.match(r"^[•\-*]\s*(?:\*\*)?Tür:(?:\*\*)?\s*(.+)$", l)
            if m_ok:
                okunus = m_ok.group(1).strip()
            elif m_tur:
                tur = m_tur.group(1).strip()
        elif section == "anlamlar":
            item = re.sub(r"^[•\-*]\s*", "", l).strip()
            if item:
                anlamlar.append(item)
        elif section == "kaliplar":
            item = re.sub(r"^[•\-*]\s*", "", l).strip()
            if item:
                kaliplar.append(item)
        elif section == "ornek":
            item = re.sub(r"^[>│]\s*", "", l).strip()
            if item:
                ornekler.append(item)

    return {
        "word": word.strip(),
        "okunus": okunus,
        "tur": tur,
        "anlamlar": anlamlar,
        "kaliplar": kaliplar,
        "ornekler": ornekler,
    }


def parse_markdown(text: str) -> list[dict]:
    lines = [clean_line(l) for l in text.splitlines()]
    if lines and lines[-1].endswith("**") and not lines[-1].startswith("**"):
        lines[-1] = lines[-1][:-2].rstrip()

    non_empty = [(i, l) for i, l in enumerate(lines) if l]
    starts = []
    for idx_in_ne, (line_no, l) in enumerate(non_empty):
        if l.startswith("## "):
            starts.append((line_no, l[3:].strip()))
        elif (
            not l.startswith("#")
            and not l.startswith("-")
            and not l.startswith("•")
            and not l.startswith("│")
            and not l.startswith(">")
            and not re.match(r"^[-─━*]+$", l)
            and l not in ("Anlamlar", "Kalıplar", "Örnek", "<!-- Yakalama -->")
        ):
            if idx_in_ne + 1 < len(non_empty):
                nxt = non_empty[idx_in_ne + 1][1]
                if re.match(r"^[•\-*]\s*(?:\*\*)?(?:Okunuş|Tür):(?:\*\*)?", nxt):
                    starts.append((line_no, l.strip()))

    entries = []
    for k, (start_line, word) in enumerate(starts):
        end_line = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
        block = [l for l in lines[start_line + 1 : end_line] if l]
        while block and (re.match(r"^[-─━*]+$", block[-1]) or block[-1].startswith("# ")):
            block.pop()
        entries.append(parse_block(word, block))
    return entries


def richness_score(e: dict) -> tuple:
    return (
        1 if e["okunus"] else 0,
        1 if e["kaliplar"] else 0,
        1 if e["ornekler"] else 0,
        len(e["anlamlar"]),
        len(e["kaliplar"]),
        len(e["ornekler"]),
        sum(len(x) for x in e["anlamlar"]),
    )


def dedupe_and_merge(entries: list[dict]) -> tuple[list[dict], int]:
    grouped: dict[str, list[dict]] = {}
    for e in entries:
        key = e["word"].strip().lower()
        grouped.setdefault(key, []).append(e)

    merged = []
    dups_removed = 0
    for key, group in grouped.items():
        if len(group) > 1:
            dups_removed += len(group) - 1
        # Sort candidates by richness descending
        group_sorted = sorted(group, key=richness_score, reverse=True)
        best = dict(group_sorted[0])
        # Normalize headword to lowercase unless it starts with "What " or is an acronym
        w = best["word"].strip()
        if not (w.isupper() and len(w) <= 5):
            w = w[0].lower() + w[1:] if w else w
        best["word"] = w

        # Fill missing fields from secondary duplicates
        for other in group_sorted[1:]:
            if not best["okunus"] and other["okunus"]:
                best["okunus"] = other["okunus"]
            if not best["tur"] and other["tur"]:
                best["tur"] = other["tur"]
            if not best["kaliplar"] and other["kaliplar"]:
                best["kaliplar"] = other["kaliplar"]
            if not best["ornekler"] and other["ornekler"]:
                best["ornekler"] = other["ornekler"]
            # If secondary has extra distinct meanings (different POS), append them
            existing_lower = {re.sub(r"\W+", "", x.lower())[:25] for x in best["anlamlar"]}
            for a in other["anlamlar"]:
                sig = re.sub(r"\W+", "", a.lower())[:25]
                if sig and sig not in existing_lower and len(best["anlamlar"]) < 6:
                    best["anlamlar"].append(a)
                    existing_lower.add(sig)

        merged.append(best)

    merged.sort(key=lambda e: e["word"].lower())
    return merged, dups_removed


def render_markdown(entries: list[dict]) -> str:
    out = [
        "# İngilizce Kelime Sözlüğü",
        "",
        f"> Toplam **{len(entries)}** benzersiz kelime · Alfabetik sıralı · Hızlı arama için `apps/vocab.html`",
        "",
    ]
    for e in entries:
        out.append(f"## {e['word']}")
        if e["okunus"]:
            out.append(f"- **Okunuş:** {e['okunus']}")
        else:
            out.append("- **Okunuş:** —")
        out.append(f"- **Tür:** {e['tur'] or '—'}")
        out.append("")
        out.append("### Anlamlar")
        for a in e["anlamlar"]:
            out.append(format_kv_bullet(a, italicize_example=True))
        if e["kaliplar"]:
            out.append("")
            out.append("### Kalıplar")
            for k in e["kaliplar"]:
                out.append(format_kv_bullet(k))
        if e["ornekler"]:
            out.append("")
            out.append("### Örnek")
            for o in e["ornekler"]:
                out.append(f"> {o}")
        out.append("")
        out.append("---")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def strip_md_inline(s: str) -> str:
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"\*(.+?)\*", r"\1", s)
    return s


def build_html(entries: list[dict]) -> str:
    # Compact payload: [word, ipa, pos, meanings[], phrases[], examples[]]
    payload = []
    for e in entries:
        payload.append([
            e["word"],
            "" if e["okunus"] == "—" else e["okunus"],
            "" if e["tur"] == "—" else e["tur"],
            [strip_md_inline(a) for a in e["anlamlar"]],
            [strip_md_inline(k) for k in e["kaliplar"]],
            e["ornekler"],
        ])
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    data_json = data_json.replace("</", "<\\/")

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sözlük · {len(entries)} Kelime</title>
<style>
  :root {{
    --bg: #171615;
    --sidebar: #1c1b19;
    --surface: #23221f;
    --border: #2b2926;
    --fg: #e7e4dc;
    --fg-soft: #b5b0a4;
    --fg-muted: #7e7a70;
    --accent: #d4a36a;
    --accent-bg: rgba(212, 163, 106, 0.12);
    --serif: Georgia, "Iowan Old Style", "Palatino Linotype", serif;
    --sans: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    --mono: ui-monospace, SFMono-Regular, Menlo, monospace;
  }}
  [data-theme="light"] {{
    --bg: #faf8f4;
    --sidebar: #f3f0ea;
    --surface: #ffffff;
    --border: #e5e0d5;
    --fg: #1f1e1b;
    --fg-soft: #4c4942;
    --fg-muted: #847f75;
    --accent: #9a6324;
    --accent-bg: rgba(154, 99, 36, 0.10);
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{ height: 100%; }}
  body {{
    font-family: var(--sans);
    background: var(--bg);
    color: var(--fg);
    line-height: 1.65;
    -webkit-font-smoothing: antialiased;
    overflow: hidden;
  }}
  .app {{
    display: grid;
    grid-template-columns: 310px 1fr;
    height: 100vh;
  }}
  .sidebar {{
    background: var(--sidebar);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    height: 100vh;
    min-width: 0;
  }}
  .sidebar-top {{
    padding: 16px 14px 12px;
    border-bottom: 1px solid var(--border);
    display: flex;
    gap: 8px;
    align-items: center;
  }}
  .search-wrap {{
    position: relative;
    flex: 1;
  }}
  #search {{
    width: 100%;
    background: var(--bg);
    border: 1px solid var(--border);
    color: var(--fg);
    padding: 9px 12px;
    border-radius: 8px;
    font-size: 0.9rem;
    outline: none;
    transition: border-color .15s;
  }}
  #search:focus {{ border-color: var(--accent); }}
  #search::placeholder {{ color: var(--fg-muted); }}
  .theme-btn {{
    background: transparent;
    border: 1px solid var(--border);
    color: var(--fg-muted);
    width: 36px;
    height: 36px;
    border-radius: 8px;
    cursor: pointer;
    font-size: 0.95rem;
    flex-shrink: 0;
  }}
  .theme-btn:hover {{ color: var(--fg); border-color: var(--accent); }}
  .sidebar-meta {{
    padding: 7px 16px;
    font-size: 0.74rem;
    color: var(--fg-muted);
    border-bottom: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
  }}
  .word-list {{
    flex: 1;
    overflow-y: auto;
    padding: 6px 8px 24px;
  }}
  .letter-sep {{
    position: sticky;
    top: -6px;
    background: var(--sidebar);
    color: var(--accent);
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    padding: 8px 10px 4px;
    z-index: 2;
  }}
  .w-item {{
    padding: 8px 10px;
    border-radius: 7px;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    gap: 1px;
    transition: background .1s;
  }}
  .w-item:hover {{ background: var(--surface); }}
  .w-item.active {{ background: var(--accent-bg); }}
  .w-item-title {{
    font-size: 0.93rem;
    font-weight: 550;
    color: var(--fg);
  }}
  .w-item.active .w-item-title {{ color: var(--accent); font-weight: 600; }}
  .w-item-sub {{
    font-size: 0.78rem;
    color: var(--fg-muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .more-btn {{
    width: 100%;
    margin-top: 8px;
    background: var(--surface);
    color: var(--fg-soft);
    border: 1px solid var(--border);
    padding: 8px;
    border-radius: 7px;
    font-size: 0.8rem;
    cursor: pointer;
  }}
  .more-btn:hover {{ border-color: var(--accent); color: var(--fg); }}
  .pane {{
    height: 100vh;
    overflow-y: auto;
    padding: 56px 48px 80px;
  }}
  .article {{
    max-width: 640px;
    margin: 0 auto;
  }}
  .headword {{
    font-family: var(--serif);
    font-size: 2.4rem;
    font-weight: 600;
    color: var(--fg);
    letter-spacing: -0.02em;
    line-height: 1.2;
  }}
  .meta-line {{
    margin-top: 10px;
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    padding-bottom: 24px;
    border-bottom: 1px solid var(--border);
  }}
  .ipa {{
    font-family: var(--mono);
    font-size: 0.9rem;
    color: var(--fg-muted);
  }}
  .pos {{
    font-size: 0.84rem;
    font-style: italic;
    color: var(--accent);
  }}
  .speak {{
    background: transparent;
    border: 1px solid var(--border);
    color: var(--fg-soft);
    padding: 3px 10px;
    border-radius: 99px;
    font-size: 0.78rem;
    cursor: pointer;
    transition: border-color .12s, color .12s;
  }}
  .speak:hover {{ border-color: var(--accent); color: var(--accent); }}
  .section {{
    margin-top: 28px;
  }}
  .sec-title {{
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--fg-muted);
    font-weight: 600;
    margin-bottom: 12px;
  }}
  .meanings {{
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }}
  .meanings li {{
    font-size: 1.02rem;
    color: var(--fg);
    padding-left: 16px;
    position: relative;
  }}
  .meanings li::before {{
    content: "";
    position: absolute;
    left: 0;
    top: 11px;
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: var(--accent);
  }}
  .phrases {{
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }}
  .phrases li {{
    font-size: 0.95rem;
    color: var(--fg-soft);
  }}
  .phrases .p-key {{
    font-family: var(--serif);
    color: var(--fg);
    font-weight: 600;
  }}
  .example {{
    border-left: 2px solid var(--accent);
    padding: 4px 0 4px 18px;
  }}
  .example .en {{
    font-family: var(--serif);
    font-size: 1.06rem;
    color: var(--fg);
    line-height: 1.65;
  }}
  .example .tr {{
    display: block;
    margin-top: 6px;
    font-size: 0.92rem;
    color: var(--fg-muted);
  }}
  .hint {{
    margin-top: 48px;
    font-size: 0.76rem;
    color: var(--fg-muted);
  }}
  @media (max-width: 780px) {{
    body {{ overflow: auto; }}
    .app {{ grid-template-columns: 1fr; height: auto; }}
    .sidebar {{ height: 42vh; border-right: none; border-bottom: 1px solid var(--border); }}
    .pane {{ height: auto; padding: 28px 20px 60px; }}
    .headword {{ font-size: 1.9rem; }}
  }}
</style>
</head>
<body>
<div class="app">
  <aside class="sidebar">
    <div class="sidebar-top">
      <div class="search-wrap">
        <input id="search" type="search" placeholder="Kelime veya anlam ara..." autocomplete="off" autofocus>
      </div>
      <button class="theme-btn" id="themeBtn" title="Açık / Koyu Tema">◐</button>
    </div>
    <div class="sidebar-meta">
      <span id="stats">{len(entries)} kelime</span>
      <span>↑ ↓ gezin</span>
    </div>
    <div class="word-list" id="wordList"></div>
  </aside>

  <main class="pane">
    <article class="article" id="detail"></article>
  </main>
</div>

<script>
const RAW = {data_json};
const norm = s => (s || "").toLowerCase()
  .replace(/İ/g, "i").replace(/ı/g, "i").replace(/ş/g, "s")
  .replace(/ğ/g, "g").replace(/ü/g, "u").replace(/ö/g, "o").replace(/ç/g, "c");

const DATA = RAW.map(r => ({{
  w: r[0], ipa: r[1], pos: r[2], m: r[3], p: r[4], ex: r[5],
  wNorm: norm(r[0]),
  blob: norm([r[0], ...r[3], ...r[4], ...r[5]].join(" "))
}}));

let filtered = DATA;
let selectedIdx = 0;
let shown = 0;
const PAGE = 120;

const searchEl = document.getElementById("search");
const listEl = document.getElementById("wordList");
const detailEl = document.getElementById("detail");
const statsEl = document.getElementById("stats");
const themeBtn = document.getElementById("themeBtn");

if (localStorage.getItem("vocab-theme") === "light") document.documentElement.setAttribute("data-theme", "light");
themeBtn.onclick = () => {{
  const light = document.documentElement.getAttribute("data-theme") === "light";
  if (light) {{
    document.documentElement.removeAttribute("data-theme");
    localStorage.setItem("vocab-theme", "dark");
  }} else {{
    document.documentElement.setAttribute("data-theme", "light");
    localStorage.setItem("vocab-theme", "light");
  }}
}};

const esc = s => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

function speak(word) {{
  if (!("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(word);
  u.lang = "en-US";
  u.rate = 0.95;
  window.speechSynthesis.speak(u);
}}

function formatPhrase(line) {{
  const i = line.indexOf(":");
  if (i > 0 && i < 55) {{
    return `<span class="p-key">${{esc(line.slice(0, i))}}</span> — ${{esc(line.slice(i + 1).trim())}}`;
  }}
  return esc(line);
}}

function showDetail(idx) {{
  selectedIdx = idx;
  const item = filtered[idx];
  if (!item) {{
    detailEl.innerHTML = `<p style="color:var(--fg-muted)">Sonuç bulunamadı.</p>`;
    return;
  }}

  listEl.querySelectorAll(".w-item.active").forEach(x => x.classList.remove("active"));
  const activeNode = listEl.querySelector(`.w-item[data-i="${{idx}}"]`);
  if (activeNode) {{
    activeNode.classList.add("active");
    activeNode.scrollIntoView({{ block: "nearest" }});
  }}

  const meaningsHtml = item.m.map(x => `<li>${{esc(x)}}</li>`).join("");
  const phrasesHtml = item.p.length
    ? `<section class="section"><div class="sec-title">Kalıplar</div><ul class="phrases">${{item.p.map(x => `<li>${{formatPhrase(x)}}</li>`).join("")}}</ul></section>`
    : "";
  let exHtml = "";
  if (item.ex.length) {{
    const lines = item.ex.map(l =>
      l.startsWith("(") ? `<span class="tr">${{esc(l.replace(/^\\(|\\)$/g, ""))}}</span>` : `<div class="en">${{esc(l)}}</div>`
    ).join("");
    exHtml = `<section class="section"><div class="sec-title">Örnek</div><div class="example">${{lines}}</div></section>`;
  }}

  detailEl.innerHTML = `
    <h1 class="headword">${{esc(item.w)}}</h1>
    <div class="meta-line">
      ${{item.ipa ? `<span class="ipa">${{esc(item.ipa)}}</span>` : ""}}
      ${{item.pos ? `<span class="pos">${{esc(item.pos)}}</span>` : ""}}
      <button class="speak" id="speakBtn">Dinle</button>
    </div>
    <section class="section">
      <div class="sec-title">Anlam</div>
      <ul class="meanings">${{meaningsHtml}}</ul>
    </section>
    ${{phrasesHtml}}
    ${{exHtml}}
    <div class="hint">Kısayollar: <strong>/</strong> ara · <strong>↑ ↓</strong> önceki/sonraki kelime</div>
  `;
  document.getElementById("speakBtn").onclick = () => speak(item.w);
}}

let lastLetter = "";
function renderMore() {{
  const oldMore = document.getElementById("moreBtn");
  if (oldMore) oldMore.remove();

  const frag = document.createDocumentFragment();
  const end = Math.min(shown + PAGE, filtered.length);
  for (let i = shown; i < end; i++) {{
    const item = filtered[i];
    const lt = (item.w[0] || "#").toUpperCase();
    if (!searchEl.value.trim() && lt !== lastLetter) {{
      lastLetter = lt;
      const sep = document.createElement("div");
      sep.className = "letter-sep";
      sep.textContent = lt;
      frag.appendChild(sep);
    }}
    const row = document.createElement("div");
    row.className = "w-item" + (i === selectedIdx ? " active" : "");
    row.dataset.i = i;
    row.innerHTML = `<div class="w-item-title">${{esc(item.w)}}</div><div class="w-item-sub">${{esc(item.m[0] || "")}}</div>`;
    row.onclick = () => showDetail(i);
    frag.appendChild(row);
  }}
  shown = end;
  if (shown < filtered.length) {{
    const btn = document.createElement("button");
    btn.id = "moreBtn";
    btn.className = "more-btn";
    btn.textContent = `Daha fazla (${{shown}} / ${{filtered.length}})`;
    btn.onclick = renderMore;
    frag.appendChild(btn);
  }}
  listEl.appendChild(frag);
}}

function applyFilter() {{
  const q = norm(searchEl.value.trim());
  filtered = q ? DATA.filter(x => x.blob.includes(q)) : DATA;
  if (q) {{
    filtered = [...filtered].sort((a, b) => {{
      const r = x => x.wNorm === q ? 0 : x.wNorm.startsWith(q) ? 1 : x.wNorm.includes(q) ? 2 : 3;
      return r(a) - r(b) || a.wNorm.localeCompare(b.wNorm);
    }});
  }}
  statsEl.textContent = filtered.length === DATA.length ? `${{DATA.length}} kelime` : `${{filtered.length}} / ${{DATA.length}}`;
  listEl.innerHTML = "";
  shown = 0;
  lastLetter = "";
  selectedIdx = 0;
  renderMore();
  showDetail(0);
}}

let t;
searchEl.addEventListener("input", () => {{ clearTimeout(t); t = setTimeout(applyFilter, 50); }});

document.addEventListener("keydown", e => {{
  if (e.key === "/" && document.activeElement !== searchEl) {{
    e.preventDefault(); searchEl.focus(); searchEl.select();
  }} else if (e.key === "Escape" && document.activeElement === searchEl) {{
    searchEl.value = ""; applyFilter();
  }} else if (e.key === "ArrowDown" && filtered.length) {{
    e.preventDefault();
    const nxt = Math.min(selectedIdx + 1, filtered.length - 1);
    if (nxt >= shown) renderMore();
    showDetail(nxt);
  }} else if (e.key === "ArrowUp" && filtered.length) {{
    e.preventDefault();
    showDetail(Math.max(selectedIdx - 1, 0));
  }}
}});

applyFilter();
</script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="Normalize vocabulary.md and build offline vocab HTML")
    parser.add_argument("--import-inbox", action="store_true", help="Import & merge notes/00-inbox.md into vocabulary.md")
    parser.add_argument("--normalize", action="store_true", help="Deduplicate & alphabetically sort vocabulary.md")
    parser.add_argument("--input", type=Path, default=None, help="Override input vocabulary.md path")
    parser.add_argument("--output", type=Path, default=None, help="Override output HTML path")
    args = parser.parse_args()

    vocab_md = args.input or VOCAB_MD
    vocab_html = args.output or VOCAB_HTML

    entries = []
    if vocab_md.exists():
        entries.extend(parse_markdown(vocab_md.read_text(encoding="utf-8")))

    inbox_count = 0
    if args.import_inbox and INBOX_MD.exists():
        inbox_entries = parse_markdown(INBOX_MD.read_text(encoding="utf-8"))
        inbox_count = len(inbox_entries)
        entries.extend(inbox_entries)

    if args.import_inbox or args.normalize or not vocab_md.exists():
        merged, dups_removed = dedupe_and_merge(entries)
        vocab_md.parent.mkdir(parents=True, exist_ok=True)
        vocab_md.write_text(render_markdown(merged), encoding="utf-8")
        print(f"Wrote {vocab_md}: {len(merged)} unique words (imported {inbox_count} from inbox, removed {dups_removed} duplicates)")
        entries = merged
    else:
        print(f"Loaded {vocab_md}: {len(entries)} words")

    vocab_html.parent.mkdir(parents=True, exist_ok=True)
    vocab_html.write_text(build_html(entries), encoding="utf-8")
    size_kb = vocab_html.stat().st_size / 1024
    print(f"Wrote {vocab_html}: {len(entries)} words ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
