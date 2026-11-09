#!/usr/bin/env python3
"""Render self-hosted statistics cards (profile overview, organization) as SVG."""

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

WIDTH, HEIGHT = 880, 206
ORG_HEIGHT = 128
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
    steps = [0.0, 0.20, 0.36, 0.50, 0.62]
    return [tint(accent, steps[min(i, len(steps) - 1)]) for i in range(count)]


def org_metrics(name):
    repos = gh_api("/orgs/%s/repos?per_page=100&type=public" % name)
    return [("repo", "Repositories", len(repos)),
            ("star", "Total Stars", sum(r["stargazers_count"] for r in repos)),
            ("repo-forked", "Total Forks", sum(r["forks_count"] for r in repos))]


def user_metrics(name, orgs):
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
    return [("star", "Stars", sum(r["stargazers_count"] for r in repos)),
            ("git-commit", "Commits %d" % year, commits),
            ("git-pull-request", "Pull Requests", search_count("issues", "author:%s+type:pr" % name)),
            ("issue-opened", "Issues", search_count("issues", "author:%s+type:issue" % name)),
            ("repo", "Repos", len(repos))]


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


def icon(name, x, y, size, color):
    lines = ['  <svg x="%.1f" y="%.1f" width="%d" height="%d" viewBox="%s" fill="%s">'
             % (x, y, size, size, OCTICON, color)]
    lines += ['    <path fill-rule="evenodd" d="%s"/>' % path for path in ICONS[name]]
    lines.append("  </svg>")
    return lines


def open_card(c, height=HEIGHT):
    return [
        '<svg width="%d" height="%d" viewBox="0 0 %d %d" fill="none" xmlns="http://www.w3.org/2000/svg" role="img">'
        % (WIDTH, height, WIDTH, height),
        "  <style>",
        "    .title { font: 600 16px %s; fill: %s; }" % (FONT, c["title"]),
        "    .eyebrow { font: 600 9.5px %s; fill: %s; letter-spacing: 1.5px; }" % (FONT, c["muted"]),
        "    .hero { font: 700 28px %s; fill: %s; letter-spacing: -0.4px; }" % (FONT, c["accent"]),
        "    .value { font: 700 22px %s; fill: %s; }" % (FONT, c["accent"]),
        "    .stat { font: 700 15px %s; fill: %s; }" % (FONT, c["accent"]),
        "    .label { font: 500 9px %s; fill: %s; letter-spacing: 1px; }" % (FONT, c["muted"]),
        "    .lang { font: 600 10px %s; fill: %s; letter-spacing: 0.9px; }" % (FONT, c["muted"]),
        "    .pct { font: 700 11px %s; fill: %s; }" % (FONT, c["accent"]),
        "  </style>",
        '  <rect x="0.5" y="0.5" width="%d" height="%d" rx="12" fill="%s" stroke="%s"/>'
        % (WIDTH - 1, height - 1, c["bg"], c["border"]),
    ]


def write_card(out, lines):
    with open(out, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines + ["</svg>"]) + "\n")


def render_overview(name, metrics, languages, theme, out):
    c = THEMES[theme]
    split = WIDTH // 2
    hero, hero_label, hero_value = metrics[0]
    lines = open_card(c)
    lines.append('  <text class="title" x="%d" y="40">%s</text>' % (PAD, name))
    lines.append('  <text class="eyebrow" x="%d" y="40" text-anchor="end">ALL REPOSITORIES</text>'
                 % (split - PAD))
    lines.append('  <text class="title" x="%d" y="40">Languages</text>' % (split + PAD))
    lines.append('  <text class="eyebrow" x="%d" y="40" text-anchor="end">BY CODE SIZE</text>'
                 % (WIDTH - PAD))
    lines.append('  <line x1="%d" y1="56" x2="%d" y2="56" stroke="%s"/>'
                 % (PAD, WIDTH - PAD, c["divider"]))
    lines.append('  <line x1="%d" y1="74" x2="%d" y2="%d" stroke="%s"/>'
                 % (split, split, HEIGHT - 18, c["divider"]))

    lines += icon(hero, PAD, 80, 20, c["accent"])
    lines.append('  <text class="hero" x="%d" y="101">%s</text>' % (PAD + 30, compact(hero_value)))
    lines.append('  <text class="label" x="%d" y="120">%s</text>' % (PAD + 31, hero_label.upper()))
    lines.append('  <line x1="%d" y1="130" x2="%d" y2="130" stroke="%s"/>'
                 % (PAD, split - PAD, c["divider"]))
    mid = split // 2
    for index, (name_, label, value) in enumerate(metrics[1:]):
        x = PAD if index % 2 == 0 else mid + 12
        end = mid - 12 if index % 2 == 0 else split - PAD
        y = 158 + (index // 2) * 28
        lines += icon(name_, x, y - 10, 11, c["muted"])
        lines.append('  <text class="lang" x="%d" y="%d">%s</text>' % (x + 16, y, label.upper()))
        lines.append('  <text class="stat" x="%d" y="%d" text-anchor="end">%s</text>'
                     % (end, y, compact(value)))

    shades = ramp(c["accent"], len(languages))
    bar_x = split + PAD
    bar_w = WIDTH - PAD - bar_x
    for index, ((lang, share), shade) in enumerate(zip(languages, shades)):
        y = 84 + index * 25
        lines.append('  <circle cx="%.1f" cy="%.1f" r="3.5" fill="%s"/>' % (bar_x + 3.5, y - 4, shade))
        lines.append('  <text class="lang" x="%d" y="%d">%s</text>' % (bar_x + 14, y, lang.upper()))
        lines.append('  <text class="pct" x="%d" y="%d" text-anchor="end">%.1f%%</text>'
                     % (WIDTH - PAD, y, share * 100))
        lines.append('  <rect x="%d" y="%d" width="%d" height="4" rx="2" fill="%s"/>'
                     % (bar_x, y + 5, bar_w, c["track"]))
        lines.append('  <rect x="%d" y="%d" width="%.1f" height="4" rx="2" fill="%s"/>'
                     % (bar_x, y + 5, max(share * bar_w, 6), shade))
    write_card(out, lines)


def render_org(name, metrics, theme, out):
    c = THEMES[theme]
    lines = open_card(c, ORG_HEIGHT)
    lines.append('  <text class="eyebrow" x="%d" y="66">ORGANIZATION</text>' % PAD)
    lines.append('  <text class="title" x="%d" y="92">%s</text>' % (PAD, name))
    lines.append('  <line x1="250" y1="42" x2="250" y2="%d" stroke="%s"/>'
                 % (ORG_HEIGHT - 22, c["divider"]))
    step = (WIDTH - PAD - 266) / float(len(metrics))
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
        metrics = user_metrics(args.name, orgs)
        languages = languages_for(args.name)
        draw = lambda theme, out: render_overview(args.name, metrics, languages, theme, out)

    draw(args.theme, args.out)
    if args.also_dark:
        dark_out = args.out[:-4] + "-dark.svg" if args.out.endswith(".svg") else args.out + "-dark"
        draw("dark", dark_out)


if __name__ == "__main__":
    main()
