#!/usr/bin/env python3
"""Generate candy-themed GitHub stats + language SVGs from the GitHub GraphQL API.

Pure stdlib (no dependencies). Reads GITHUB_TOKEN / STATS_TOKEN from the
environment and writes assets/stats.svg + assets/languages.svg. Designed to run
both locally and inside the daily GitHub Action in this repo.
"""
import json
import os
import sys
import urllib.request

LOGIN = os.environ.get("GITHUB_LOGIN", "lumduan")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("STATS_TOKEN")
FONT = "font-family=\"'Segoe UI','Helvetica Neue',Helvetica,Arial,sans-serif\""
LANG_COLORS = ["#E85A9C", "#9B7BD8", "#7BC9B0", "#FFC36B", "#6BB8E8", "#D88BFF"]
# Languages to exclude from the card — these inflate byte counts without
# reflecting engineering work: Jupyter Notebook is .ipynb JSON (double-counts as
# Python); HTML here comes from docs/portfolio sites, not application code.
LANG_EXCLUDE = {"Jupyter Notebook", "HTML"}

QUERY = """
query($login: String!) {
  user(login: $login) {
    createdAt
    followers { totalCount }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) {
      totalCount
      nodes {
        stargazerCount
        forkCount
        languages(first: 12, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
    }
    contributionsCollection { totalCommitContributions }
  }
}
"""


def gql():
    body = json.dumps({"query": QUERY, "variables": {"login": LOGIN}}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={
            "Authorization": f"bearer {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "lumduan-profile-stats",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt(n):
    if n >= 1000:
        return f"{n/1000:.1f}k".replace(".0k", "k")
    return str(n)


def _update_readme_block(block_content):
    """Replace the stats block in README.md between the STATS markers
    (auto-refreshed by the daily Action, so the profile shows live stats
    as markdown tables with no image dependency)."""
    import re
    try:
        text = open("README.md", encoding="utf-8").read()
    except FileNotFoundError:
        return
    start, end = "<!-- STATS:START -->", "<!-- STATS:END -->"
    if start not in text or end not in text:
        return
    block = f"{start}\n{block_content}\n{end}"
    text = re.sub(re.escape(start) + ".*?" + re.escape(end), block, text, flags=re.DOTALL)
    open("README.md", "w", encoding="utf-8").write(text)


def main():
    if not TOKEN:
        print("ERROR: GITHUB_TOKEN (or STATS_TOKEN) not set", file=sys.stderr)
        sys.exit(1)

    data = gql()
    if "errors" in data:
        print(data["errors"], file=sys.stderr)
        sys.exit(1)

    u = data["data"]["user"]
    repos = u["repositories"]["nodes"]
    total_stars = sum(r["stargazerCount"] for r in repos)
    total_forks = sum(r["forkCount"] for r in repos)
    repo_count = u["repositories"]["totalCount"]
    followers = u["followers"]["totalCount"]
    commits = u["contributionsCollection"]["totalCommitContributions"]
    since = (u["createdAt"] or "2015")[:4]

    # aggregate language bytes across owned, non-fork, public repos
    lang_bytes = {}
    for r in repos:
        for e in (r.get("languages") or {}).get("edges", []):
            name = e["node"]["name"]
            if name in LANG_EXCLUDE:
                continue
            lang_bytes[name] = lang_bytes.get(name, 0) + e["size"]
    top = sorted(lang_bytes.items(), key=lambda kv: kv[1], reverse=True)[:6]
    total_lang = sum(v for _, v in top) or 1

    os.makedirs("assets", exist_ok=True)

    # ---- stats card (460 x 180, 3x2 tile grid) ----
    tiles = [
        (fmt(total_stars), "Stars", "#E85A9C"),
        (fmt(repo_count), "Public repos", "#9B7BD8"),
        (fmt(followers), "Followers", "#7BC9B0"),
        (fmt(commits), "Commits (1y)", "#FFC36B"),
        (str(since), "Member since", "#6BB8E8"),
        (fmt(total_forks), "Forks", "#D88BFF"),
    ]
    cw, ch = 460, 180
    pad_x, top_y, cols, rows_n = 18, 56, 3, 2
    col_w = (cw - 2 * pad_x) / cols
    row_h = (ch - top_y - 14) / rows_n
    tile_svg = []
    for i, (val, label, color) in enumerate(tiles):
        ci, ri = i % cols, i // cols
        cx = pad_x + col_w * ci + col_w / 2
        cy = top_y + row_h * ri + row_h / 2
        tile_svg.append(
            f'<text x="{cx:.0f}" y="{cy - 2:.0f}" text-anchor="middle" '
            f'font-size="26" font-weight="800" fill="#6A4AA8" {FONT}>{esc(val)}</text>'
        )
        tile_svg.append(f'<circle cx="{cx - 34:.0f}" cy="{cy + 19:.0f}" r="4" fill="{color}"/>')
        tile_svg.append(
            f'<text x="{cx - 25:.0f}" y="{cy + 23:.0f}" font-size="11" '
            f'font-weight="600" fill="#6A5A7A" {FONT}>{esc(label)}</text>'
        )
    stats_svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{cw}" height="{ch}" '
        f'viewBox="0 0 {cw} {ch}" role="img" aria-label="lumduan GitHub stats">\n'
        f'<rect width="{cw}" height="{ch}" rx="14" fill="#FFFFFF"/>\n'
        f'<text x="20" y="31" font-size="15" font-weight="800" fill="#E85A9C" {FONT}>'
        f'lumduan · GitHub stats</text>\n'
        f'<circle cx="{cw - 28}" cy="25" r="6" fill="#FFC36B"/>'
        f'<circle cx="{cw - 14}" cy="25" r="6" fill="#E85A9C"/>\n'
        + "\n".join(tile_svg)
        + "\n</svg>"
    )
    with open("assets/stats.svg", "w") as f:
        f.write(stats_svg)

    # ---- languages card (340 x 180, up to 6 bars) ----
    lw, lh = 340, 180
    rows_svg = []
    for i, (name, _bytes) in enumerate(top):
        pct = _bytes * 100 / total_lang
        y = 50 + i * 21
        color = LANG_COLORS[i % len(LANG_COLORS)]
        bar_w = 292 * pct / 100
        rows_svg.append(
            f'<text x="20" y="{y + 9:.0f}" font-size="12" font-weight="700" '
            f'fill="#3A2A4D" {FONT}>{esc(name)}</text>'
        )
        rows_svg.append(
            f'<text x="{lw - 20}" y="{y + 9:.0f}" text-anchor="end" font-size="12" '
            f'font-weight="600" fill="#6A5A7A" {FONT}>{pct:.1f}%</text>'
        )
        rows_svg.append(f'<rect x="20" y="{y + 13:.0f}" width="292" height="6" rx="3" fill="#F1E6F4"/>')
        rows_svg.append(
            f'<rect x="20" y="{y + 13:.0f}" width="{bar_w:.0f}" height="6" rx="3" fill="{color}"/>'
        )
    langs_svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{lw}" height="{lh}" '
        f'viewBox="0 0 {lw} {lh}" role="img" aria-label="lumduan most used languages">\n'
        f'<rect width="{lw}" height="{lh}" rx="14" fill="#FFFFFF"/>\n'
        f'<text x="20" y="31" font-size="15" font-weight="800" fill="#E85A9C" {FONT}>'
        f'Most-used languages</text>\n'
        + "\n".join(rows_svg)
        + "\n</svg>"
    )
    with open("assets/languages.svg", "w") as f:
        f.write(langs_svg)

    # markdown-table stats block in README (auto-refreshed by this Action)
    _stats_rows = [
        ("Stars", str(total_stars)),
        ("Public repos", str(repo_count)),
        ("Followers", str(followers)),
        ("Commits (1y)", fmt(commits)),
        ("Forks", str(total_forks)),
        ("Member since", str(since)),
    ]
    _stats_tbl = "| Metric | Value |\n|---|---:|\n" + "\n".join(
        f"| {k} | {v} |" for k, v in _stats_rows)
    _lang_rows = [
        f"| {n} | {b*100/total_lang:.0f}% |" if b*100/total_lang >= 1
        else f"| {n} | <1% |" for n, b in top
    ]
    _langs_tbl = "| Language | Share |\n|---|---:|\n" + "\n".join(_lang_rows)
    _update_readme_block(_stats_tbl + "\n\n" + _langs_tbl)

    print(f"OK: stars={total_stars} repos={repo_count} followers={followers} "
          f"commits1y={commits} forks={total_forks} since={since}")
    print(f"    langs: {[(n, round(b*100/total_lang,1)) for n,b in top]}")


if __name__ == "__main__":
    main()
