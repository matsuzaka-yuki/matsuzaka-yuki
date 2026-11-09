#!/usr/bin/env python3
"""Render self-hosted statistics cards (profile row, organization band) as SVG."""

import argparse
import datetime
import json
import math
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = "Inter, 'Segoe UI', Ubuntu, 'Helvetica Neue', Arial, sans-serif"
OCTICON = "0 0 16 16"
ICONS = json.load(open(os.path.join(HERE, "octicons.json"), encoding="utf-8"))

THEMES = {
    "blue": {
        "bg": "#FFFFFF", "border": "#DBE3F0", "title": "#0F172A",
        "muted": "#667085", "accent": "#2563EB", "divider": "#EAECF0",
        "track": "#EEF2F6",
    },
    "brand": {
        "bg": "#FFFFFF", "border": "#EDD8DD", "title": "#0F172A",
        "muted": "#667085", "accent": "#EE8FA8", "divider": "#F5E4E8",
        "track": "#F7EEF1",
    },
    "dark": {
        "bg": "#0D1117", "border": "#30363D", "title": "#E6EDF3",
        "muted": "#8B949E", "accent": "#58A6FF", "divider": "#21262D",
        "track": "#161B22",
    },
}

WIDTH = 880
CARD_W, CARD_H = 428, 195
CARD_GAP = 24
ORG_HEIGHT = 128
INNER = 25


def gh_api(path, paginate=True, optional=False):
    """Run gh api. With optional=True an unreadable resource yields None instead of
    aborting the run; some repositories are blocked (HTTP 451) and cannot be read."""
    cmd = ["gh", "api"]
    if paginate:
        cmd += ["--paginate", "--slurp"]
    cmd.append(path)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        if optional:
            return None
        raise SystemExit("gh api failed for %s: %s" % (path, proc.stderr.strip()))
    payload = json.loads(proc.stdout)
    if not paginate:
        return payload
    items = []
    for page in payload:
        items.extend(page if isinstance(page, list) else [page])
    return items


def search_count(kind, query):
    return gh_api("/search/%s?q=%s&per_page=1" % (kind, query), paginate=False)["total_count"]


def profile_totals(name):
    """Followers and the number of repositories the account has contributed to."""
    query = ("query{user(login:\"%s\"){followers{totalCount} "
             "repositoriesContributedTo(first:1,includeUserRepositories:true){totalCount}}}" % name)
    proc = subprocess.run(["gh", "api", "graphql", "-f", "query=" + query],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit("gh api graphql failed: %s" % proc.stderr.strip())
    user = json.loads(proc.stdout)["data"]["user"]
    return user["followers"]["totalCount"], user["repositoriesContributedTo"]["totalCount"]


def compact(number):
    if number >= 10000:
        return "%.1fk" % (number / 1000.0)
    return "{:,}".format(number)


def tint(accent, ratio):
    accent = accent.lstrip("#")
    parts = [int(accent[i:i + 2], 16) for i in (0, 2, 4)]
    return "#%02X%02X%02X" % tuple(int(round(c + (255 - c) * ratio)) for c in parts)


def ramp(accent, count):
    steps = [0.0, 0.20, 0.36, 0.50, 0.62]
    return [tint(accent, steps[min(i, len(steps) - 1)]) for i in range(count)]


def org_metrics(name):
    repos = gh_api("/orgs/%s/repos?per_page=100&type=public" % name)
    return [("repo", "Repositories", len(repos)),
            ("star", "Total Stars", sum(r["stargazers_count"] for r in repos)),
            ("repo-forked", "Total Forks", sum(r["forks_count"] for r in repos))]


def user_stats(name, orgs):
    # Everything the account is responsible for: its own repositories plus the public
    # repositories of the organizations it belongs to, the same span the reference
    # profile covers with role=OWNER,ORGANIZATION_MEMBER. Forks count too: they are
    # repositories under the account and dropping them lost 49 stars.
    repos = [r for r in gh_api("/users/%s/repos?per_page=100&type=owner" % name)
             if not r["private"]]
    for org in orgs:
        repos += [r for r in (gh_api("/orgs/%s/repos?per_page=100&type=public" % org) or [])
                  if not r["private"]]
    year = datetime.date.today().year
    scopes = ["user:" + name] + ["org:" + org for org in orgs]
    commits = sum(search_count("commits", "author:%s+%s+committer-date:>=%d-01-01" % (name, s, year))
                  for s in scopes)
    followers, contributed = profile_totals(name)
    return {
        "stars": sum(r["stargazers_count"] for r in repos),
        "commits": commits,
        "prs": search_count("issues", "author:%s+type:pr" % name),
        "issues": search_count("issues", "author:%s+type:issue" % name),
        "contributed": contributed,
        "followers": followers,
        "year": year,
    }


def languages_for(name):
    """Aggregate the public repositories over REST. GraphQL would return whatever the
    calling token can see, so a local run and the workflow would disagree."""
    totals = {}
    for repo in gh_api("/users/%s/repos?per_page=100&type=owner" % name):
        if repo["fork"] or repo["private"]:
            continue  # languages describe the code written here, not upstream projects
        sizes = gh_api("/repos/%s/languages" % repo["full_name"], paginate=False, optional=True)
        for lang, size in (sizes or {}).items():
            totals[lang] = totals.get(lang, 0) + size
    overall = float(sum(totals.values())) or 1.0
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:5]
    return [(lang, size / overall) for lang, size in ranked]


def rank_percentile(stats):
    """Weighted rank over the usual medians: lower means a stronger profile."""
    cdf = lambda value: 1 - 2 ** (-value)
    parts = ((stats["commits"], 1000, 2), (stats["prs"], 50, 3), (stats["issues"], 25, 1),
             (stats["stars"], 50, 4), (stats["followers"], 10, 1))
    return 100 * (1 - sum(weight * cdf(value / float(median)) for value, median, weight in parts)
                  / 11.0)


def rank_level(percentile):
    levels = ("S+", "S", "A+", "A", "B+", "B", "C+", "C", "D")
    thresholds = (1, 12.5, 25, 37.5, 50, 62.5, 75, 87.5, 100)
    for level, threshold in zip(levels, thresholds):
        if percentile <= threshold:
            return level
    return "D"


def icon(name, x, y, size, color):
    lines = ['  <svg x="%.1f" y="%.1f" width="%d" height="%d" viewBox="%s" fill="%s">'
             % (x, y, size, size, OCTICON, color)]
    lines += ['    <path fill-rule="evenodd" d="%s"/>' % path for path in ICONS[name]]
    lines.append("  </svg>")
    return lines


def open_document(c, height):
    return [
        '<svg width="%d" height="%d" viewBox="0 0 %d %d" fill="none" xmlns="http://www.w3.org/2000/svg" role="img">'
        % (WIDTH, height, WIDTH, height),
        "  <style>",
        "    .title { font: 600 18px %s; fill: %s; }" % (FONT, c["accent"]),
        "    .row { font: 600 13.5px %s; fill: %s; }" % (FONT, c["title"]),
        "    .num { font: 700 13.5px %s; fill: %s; }" % (FONT, c["title"]),
        "    .legend { font: 600 12.5px %s; fill: %s; }" % (FONT, c["title"]),
        "    .pct { font: 600 12.5px %s; fill: %s; }" % (FONT, c["muted"]),
        "    .rank { font: 800 22px %s; fill: %s; }" % (FONT, c["title"]),
        "    .value { font: 700 22px %s; fill: %s; }" % (FONT, c["title"]),
        "    .label { font: 500 9px %s; fill: %s; letter-spacing: 1px; }" % (FONT, c["muted"]),
        "    .eyebrow { font: 600 9.5px %s; fill: %s; letter-spacing: 1.5px; }" % (FONT, c["muted"]),
        "  </style>",
    ]


def frame(c, width=CARD_W, height=CARD_H):
    return ['  <rect x="0.5" y="0.5" width="%d" height="%d" rx="12" fill="%s" stroke="%s"/>'
            % (width - 1, height - 1, c["bg"], c["border"])]


def write_card(out, lines):
    with open(out, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines + ["</svg>"]) + "\n")


def stats_card(c, name, stats):
    rows = [("star", "Total Stars", stats["stars"]),
            ("git-commit", "Commits %d" % stats["year"], stats["commits"]),
            ("git-pull-request", "Pull Requests", stats["prs"]),
            ("issue-opened", "Issues", stats["issues"]),
            ("people", "Contributed to", stats["contributed"])]
    percentile = rank_percentile(stats)
    lines = frame(c)
    lines.append('  <text class="title" x="%d" y="32">%s\'s GitHub Stats</text>' % (INNER, name))
    for index, (name_, label, value) in enumerate(rows):
        y = 66 + index * 25
        lines += icon(name_, INNER, y - 11, 16, c["accent"])
        lines.append('  <text class="row" x="%d" y="%d">%s</text>' % (INNER + 23, y, label))
        lines.append('  <text class="num" x="%d" y="%d">%s</text>'
                     % (232, y, compact(value)))
    circumference = 2 * math.pi * 35
    lines.append('  <circle cx="385" cy="100" r="35" fill="none" stroke="%s" stroke-width="6" opacity="0.2"/>'
                 % c["accent"])
    lines.append('  <circle cx="385" cy="100" r="35" fill="none" stroke="%s" stroke-width="6" '
                 'stroke-linecap="round" stroke-dasharray="%.2f" stroke-dashoffset="%.2f" '
                 'transform="rotate(-90 385 100)" opacity="0.8"/>'
                 % (c["accent"], circumference, circumference * percentile / 100.0))
    lines.append('  <text class="rank" x="385" y="108" text-anchor="middle">%s</text>'
                 % rank_level(percentile))
    return lines


def langs_card(c, languages):
    shades = ramp(c["accent"], len(languages))
    bar_x, bar_w, bar_h = INNER, CARD_W - 2 * INNER, 8
    lines = frame(c)
    lines.append('  <text class="title" x="%d" y="32">Most Used Languages</text>' % INNER)
    lines.append('  <rect x="%d" y="48" width="%d" height="%d" rx="%d" fill="%s"/>'
                 % (bar_x, bar_w, bar_h, bar_h // 2, c["track"]))
    cursor = bar_x
    for share, shade in zip([s for _, s in languages], shades):
        width = max(share * bar_w - 2, 4)
        lines.append('  <rect x="%.1f" y="48" width="%.1f" height="%d" rx="%d" fill="%s"/>'
                     % (cursor, width, bar_h, bar_h // 2, shade))
        cursor += width + 2
    for index, ((lang, share), shade) in enumerate(zip(languages, shades)):
        y = 80 + index * 24
        lines.append('  <circle cx="%d" cy="%d" r="4" fill="%s"/>' % (INNER + 4, y - 4, shade))
        lines.append('  <text class="legend" x="%d" y="%d">%s</text>' % (INNER + 17, y, lang.upper()))
        lines.append('  <text class="pct" x="%d" y="%d" text-anchor="end">%.1f%%</text>'
                     % (CARD_W - INNER, y, share * 100))
    return lines


def render_overview(name, stats, languages, theme, out):
    c = THEMES[theme]
    lines = open_document(c, CARD_H)
    lines += stats_card(c, name, stats)
    lines.append('  <g transform="translate(%d, 0)">' % (CARD_W + CARD_GAP))
    lines += langs_card(c, languages)
    lines.append("  </g>")
    write_card(out, lines)


def render_org(name, metrics, theme, out):
    c = THEMES[theme]
    lines = open_document(c, ORG_HEIGHT)
    lines += frame(c, WIDTH, ORG_HEIGHT)
    lines.append('  <text class="eyebrow" x="%d" y="66">ORGANIZATION</text>' % INNER)
    lines.append('  <text class="title" x="%d" y="92">%s</text>' % (INNER, name))
    lines.append('  <line x1="250" y1="42" x2="250" y2="%d" stroke="%s"/>'
                 % (ORG_HEIGHT - 22, c["divider"]))
    step = (WIDTH - INNER - 266) / float(len(metrics))
    for index, (name_, label, value) in enumerate(metrics):
        center = 266 + (index + 0.5) * step
        lines += icon(name_, center - 7.5, 44, 15, c["accent"])
        lines.append('  <text class="value" x="%.1f" y="94" text-anchor="middle">%s</text>'
                     % (center, compact(value)))
        lines.append('  <text class="label" x="%.1f" y="114" text-anchor="middle">%s</text>'
                     % (center, label.upper()))
    write_card(out, lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("user", "org"), required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--theme", default="blue", choices=sorted(THEMES))
    parser.add_argument("--orgs", default="", help="comma separated organizations counted as contributions")
    parser.add_argument("--also-dark", action="store_true",
                        help="also render a prefers-color-scheme:dark twin next to --out")
    args = parser.parse_args()
    orgs = [o for o in args.orgs.split(",") if o]

    # Fetch once, draw as many times as there are colour schemes.
    if args.kind == "org":
        payload = org_metrics(args.name)
        draw = lambda theme, out: render_org(args.name, payload, theme, out)
    else:
        stats = user_stats(args.name, orgs)
        languages = languages_for(args.name)
        draw = lambda theme, out: render_overview(args.name, stats, languages, theme, out)

    draw(args.theme, args.out)
    if args.also_dark:
        dark_out = args.out[:-4] + "-dark.svg" if args.out.endswith(".svg") else args.out + "-dark"
        draw("dark", dark_out)


if __name__ == "__main__":
    main()
