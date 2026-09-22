#!/usr/bin/env python3
"""Render self-hosted statistics cards (profile, organization, languages) as SVG."""

import argparse
import datetime
import json
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

WIDTH, HEIGHT = 495, 140
PAD = 28

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


def compact(number):
    if number >= 10000:
        return "%.1fk" % (number / 1000.0)
    return "{:,}".format(number)


def tint(accent, ratio):
    accent = accent.lstrip("#")
    parts = [int(accent[i:i + 2], 16) for i in (0, 2, 4)]
    return "#%02X%02X%02X" % tuple(int(round(c + (255 - c) * ratio)) for c in parts)


def ramp(accent, count):
    steps = [0.0, 0.28, 0.48, 0.66, 0.80]
    return [tint(accent, steps[min(i, len(steps) - 1)]) for i in range(count)]


def columns(count):
    step = (WIDTH - 2 * PAD) / float(count)
    return [PAD + i * step for i in range(count + 1)]


def org_metrics(name):
    repos = gh_api("/orgs/%s/repos?per_page=100&type=public" % name)
    return [("repo", "Repositories", len(repos)),
            ("star", "Total Stars", sum(r["stargazers_count"] for r in repos)),
            ("repo-forked", "Total Forks", sum(r["forks_count"] for r in repos))]


def user_metrics(name, orgs):
    # Every repository under the account counts, forks included: that is the set the
    # card used to sum, and dropping the forks lost 49 stars.
    owned = [r for r in gh_api("/users/%s/repos?per_page=100&type=owner" % name)
             if not r["private"]]
    year = datetime.date.today().year
    scopes = ["user:" + name] + ["org:" + org for org in orgs]
    commits = sum(search_count("commits", "author:%s+%s+committer-date:>=%d-01-01" % (name, s, year))
                  for s in scopes)
    return [("star", "Stars", sum(r["stargazers_count"] for r in owned)),
            ("git-commit", "Commits %d" % year, commits),
            ("git-pull-request", "Pull Requests", search_count("issues", "author:%s+type:pr" % name)),
            ("issue-opened", "Issues", search_count("issues", "author:%s+type:issue" % name)),
            ("repo", "Repos", len(owned))]


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
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:4]
    return [(lang, size / overall) for lang, size in ranked]


def open_card(c, name, eyebrow):
    return [
        '<svg width="%d" height="%d" viewBox="0 0 %d %d" fill="none" xmlns="http://www.w3.org/2000/svg" role="img">'
        % (WIDTH, HEIGHT, WIDTH, HEIGHT),
        "  <style>",
        "    .title { font: 600 17px %s; fill: %s; }" % (FONT, c["title"]),
        "    .eyebrow { font: 600 10px %s; fill: %s; letter-spacing: 1.6px; }" % (FONT, c["muted"]),
        "    .value { font: 700 21px %s; fill: %s; }" % (FONT, c["accent"]),
        "    .label { font: 500 9px %s; fill: %s; letter-spacing: 1px; }" % (FONT, c["muted"]),
        "    .lang { font: 600 9.5px %s; fill: %s; letter-spacing: 0.9px; }" % (FONT, c["muted"]),
        "    .pct { font: 700 11px %s; fill: %s; }" % (FONT, c["accent"]),
        "  </style>",
        '  <rect x="0.5" y="0.5" width="%d" height="%d" rx="12" fill="%s" stroke="%s"/>'
        % (WIDTH - 1, HEIGHT - 1, c["bg"], c["border"]),
        '  <text class="title" x="%d" y="42">%s</text>' % (PAD, name),
        '  <text class="eyebrow" x="%d" y="42" text-anchor="end">%s</text>' % (WIDTH - PAD, eyebrow),
        '  <line x1="%d" y1="60" x2="%d" y2="60" stroke="%s"/>' % (PAD, WIDTH - PAD, c["divider"]),
    ]


def write_card(out, lines):
    with open(out, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines + ["</svg>"]) + "\n")


def render_metrics(name, eyebrow, metrics, theme, out):
    c = THEMES[theme]
    edges = columns(len(metrics))
    lines = open_card(c, name, eyebrow)
    for index, (icon, label, value) in enumerate(metrics):
        center = (edges[index] + edges[index + 1]) / 2.0
        lines.append('  <svg x="%.1f" y="72" width="13" height="13" viewBox="%s" fill="%s">'
                     % (center - 6.5, OCTICON, c["accent"]))
        for path in ICONS[icon]:
            lines.append('    <path fill-rule="evenodd" d="%s"/>' % path)
        lines.append("  </svg>")
        lines.append('  <text class="value" x="%.1f" y="109" text-anchor="middle">%s</text>'
                     % (center, compact(value)))
        lines.append('  <text class="label" x="%.1f" y="127" text-anchor="middle">%s</text>'
                     % (center, label.upper()))
        if index:
            lines.append('  <line x1="%.1f" y1="78" x2="%.1f" y2="118" stroke="%s"/>'
                         % (edges[index], edges[index], c["divider"]))
    write_card(out, lines)


def render_languages(name, languages, theme, out):
    c = THEMES[theme]
    shades = ramp(c["accent"], len(languages))
    bar_x, bar_w, bar_y, bar_h = PAD, WIDTH - 2 * PAD, 74, 10
    edges = columns(len(languages))
    lines = open_card(c, name, "MOST USED LANGUAGES")
    lines.append('  <rect x="%d" y="%d" width="%d" height="%d" rx="%d" fill="%s"/>'
                 % (bar_x, bar_y, bar_w, bar_h, bar_h // 2, c["track"]))
    cursor = bar_x
    for share, shade in zip([s for _, s in languages], shades):
        width = max(share * bar_w - 3, 5)
        lines.append('  <rect x="%.1f" y="%d" width="%.1f" height="%d" rx="%d" fill="%s"/>'
                     % (cursor, bar_y, width, bar_h, bar_h // 2, shade))
        cursor += width + 3
    for index, ((lang, share), shade) in enumerate(zip(languages, shades)):
        lines.append('  <circle cx="%.1f" cy="114" r="4" fill="%s"/>' % (edges[index] + 4, shade))
        lines.append('  <text class="lang" x="%.1f" y="117">%s</text>' % (edges[index] + 14, lang.upper()))
        lines.append('  <text class="pct" x="%.1f" y="118" text-anchor="end">%.1f%%</text>'
                     % (edges[index + 1] - 6, share * 100))
    write_card(out, lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("user", "org", "langs"), required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--theme", default="blue", choices=sorted(THEMES))
    parser.add_argument("--orgs", default="", help="comma separated organizations counted as contributions")
    args = parser.parse_args()
    orgs = [o for o in args.orgs.split(",") if o]

    if args.kind == "langs":
        render_languages(args.name, languages_for(args.name), args.theme, args.out)
    elif args.kind == "org":
        render_metrics(args.name, "ORGANIZATION", org_metrics(args.name), args.theme, args.out)
    else:
        render_metrics(args.name, "GITHUB STATS", user_metrics(args.name, orgs), args.theme, args.out)


if __name__ == "__main__":
    main()
