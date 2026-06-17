#!/usr/bin/env python3
"""Fetch the latest FOMC policy statement, diff it against the previous one,
and write a dated Markdown report under reports/.

Stdlib only (urllib, re, html, difflib) so it runs on a clean runner with no
pip install. If ANTHROPIC_API_KEY is set in the environment, a Traditional
Chinese summary is appended as a bonus; otherwise that section is skipped.

The report contains:
  - the policy rate decision (best-effort extraction)
  - the full statement text
  - a redline diff vs. the previous meeting's statement (the key signal pros read)
  - source links
"""
import datetime
import difflib
import html
import json
import os
import re
import sys
import urllib.request

INDEX = "https://www.federalreserve.gov/newsevents/pressreleases/monetary.htm"
BASE = "https://www.federalreserve.gov"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT = 60


def get(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("utf-8", "replace")


def find_statement_dates() -> list[str]:
    """Return YYYYMMDD strings for monetary-policy statements, newest first."""
    page = get(INDEX)
    dates = re.findall(r"/newsevents/pressreleases/monetary(\d{8})a\.htm", page)
    return sorted(set(dates), reverse=True)


def statement_url(yyyymmdd: str) -> str:
    return f"{BASE}/newsevents/pressreleases/monetary{yyyymmdd}a.htm"


def html_to_text(page: str) -> str:
    """Crude but dependency-free HTML -> text, focused on the article body."""
    m = re.search(r'<div[^>]*id=["\']article["\'][^>]*>(.*?)</div>\s*(?:<div|<footer|</main)',
                  page, re.S | re.I)
    body = m.group(1) if m else page
    body = re.sub(r"(?s)<(script|style|nav|header|footer).*?</\1>", " ", body)
    body = re.sub(r"(?i)</p>|<br\s*/?>", "\n", body)
    body = re.sub(r"(?s)<[^>]+>", " ", body)
    body = html.unescape(body)
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r"\n[ \t]+", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def extract_statement_core(text: str) -> str:
    """Trim boilerplate around the actual statement when markers are present."""
    start = re.search(r"(Recent indicators|The Committee|Information received)", text)
    end = re.search(r"(Voting for the monetary policy action|Implementation Note)", text)
    s = start.start() if start else 0
    e = end.start() if end else len(text)
    core = text[s:e].strip()
    return core if len(core) > 80 else text


def extract_rate(text: str) -> str:
    m = re.search(
        r"target range for the federal funds rate (?:at|to)\s+([0-9].*?percent)",
        text, re.I)
    if m:
        return m.group(1).strip()
    m = re.search(r"([0-9](?:[- ‑/]| to |[0-9.])*?\s*to\s*[0-9].*?percent)", text, re.I)
    return m.group(1).strip() if m else "(could not auto-extract — see statement text)"


def redline(prev: str, curr: str) -> str:
    prev_units = re.split(r"(?<=[.])\s+", prev)
    curr_units = re.split(r"(?<=[.])\s+", curr)
    diff = difflib.unified_diff(prev_units, curr_units,
                                fromfile="previous statement",
                                tofile="this statement", lineterm="")
    lines = [ln for ln in diff]
    if not any(ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))
               for ln in lines):
        return "_(No sentence-level wording changes detected vs. the previous statement.)_"
    return "```diff\n" + "\n".join(lines) + "\n```"


def anthropic_summary(curr_core: str, diff_text: str) -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    prompt = (
        "你是總經分析師。以下是最新一次 FOMC 聲明全文，以及它相對上一次聲明的逐句 redline。"
        "請用繁體中文，條列整理：(1) 利率決定與點陣圖/前瞻指引重點；"
        "(2) 措辭相對上次的關鍵變化代表的政策訊號（偏鷹/偏鴿）；"
        "(3) 對股市的可能短線含意。最後加一行：這是教育性分析、非投資建議。\n\n"
        f"=== 聲明全文 ===\n{curr_core}\n\n=== Redline ===\n{diff_text}\n"
    )
    payload = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": 1500,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=payload,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read().decode())
        return "".join(b.get("text", "") for b in data.get("content", []))
    except Exception as e:  # noqa: BLE001
        return f"_(Claude 摘要產生失敗：{e})_"


def main() -> int:
    dates = find_statement_dates()
    if not dates:
        print("ERROR: no statements found on the index page", file=sys.stderr)
        return 1
    curr_date = dates[0]
    prev_date = dates[1] if len(dates) > 1 else None

    curr_page = get(statement_url(curr_date))
    curr_text = html_to_text(curr_page)
    curr_core = extract_statement_core(curr_text)
    rate = extract_rate(curr_text)

    prev_core = ""
    if prev_date:
        prev_core = extract_statement_core(html_to_text(get(statement_url(prev_date))))

    diff_text = redline(prev_core, curr_core) if prev_core else "_(no previous statement)_"

    d = datetime.datetime.strptime(curr_date, "%Y%m%d").date()
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_tpe = now_utc + datetime.timedelta(hours=8)

    out = []
    out.append(f"# FOMC 聲明速報 — {d.isoformat()}\n")
    out.append(f"- 抓取時間：{now_utc:%Y-%m-%d %H:%M} UTC（台灣 {now_tpe:%Y-%m-%d %H:%M}）")
    out.append(f"- 利率決定（自動擷取）：**{rate}**")
    out.append(f"- 聲明原文：{statement_url(curr_date)}")
    if prev_date:
        pd = datetime.datetime.strptime(prev_date, "%Y%m%d").date()
        out.append(f"- 對比上一次（{pd.isoformat()}）：{statement_url(prev_date)}")
    out.append("\n## 相對上次聲明的措辭變化（redline）\n")
    out.append(diff_text)
    out.append("\n## 本次聲明全文\n")
    out.append(curr_core)

    summary = anthropic_summary(curr_core, diff_text)
    if summary:
        out.append("\n## 繁中重點摘要（Claude 自動產生）\n")
        out.append(summary)

    os.makedirs("reports", exist_ok=True)
    path = os.path.join("reports", f"fomc-{d.isoformat()}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print(f"Wrote {path} (rate: {rate})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
