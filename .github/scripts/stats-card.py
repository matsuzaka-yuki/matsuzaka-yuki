#!/usr/bin/env python3
"""Render a self-hosted GitHub statistics card (user or organization) as SVG."""

import argparse
import json
import subprocess

FONT = "Inter, 'Segoe UI', Ubuntu, 'Helvetica Neue', Arial, sans-serif"

THEMES = {
    "light": {
        "bg": "#FFFFFF", "border": "#E4E7EC", "title": "#0F172A",
        "muted": "#667085", "accent": "#2563EB", "divider": "#EAECF0",
    },
    "dark": {
        "bg": "#0D1117", "border": "#30363D", "title": "#E6EDF3",
        "muted": "#8B949E", "accent": "#58A6FF", "divider": "#21262D",
    },
    "tokyonight": {
        "bg": "#1A1B27", "border": "#2F334D", "title": "#C0CAF5",
        "muted": "#565F89", "accent": "#70A5FD", "divider": "#2F334D",
    },
    "brand": {
        "bg": "#FFFFFF", "border": "#EDD8DD", "title": "#0F172A",
        "muted": "#667085", "accent": "#EE8FA8", "divider": "#F5E4E8",
    },
}

WIDTH, HEIGHT = 495, 140
PAD = 28
COLUMNS = (28.0, 173.5, 320.5, 467.0)


def gh_json(path):
    proc = subprocess.run(
        ["gh", "api", "--paginate", "--slurp", path],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SystemExit("gh api failed for %s: %s" % (path, proc.stderr.strip()))
    items = []
    for page in json.loads(proc.stdout):
        items.extend(page if isinstance(page, list) else [page])
    return items


def compact(number):
    if number >= 10000:
        return "%.1fk" % (number / 1000.0)
    return "{:,}".format(number)


def metrics_for(kind, name):
    if kind == "org":
        repos = gh_json("/orgs/%s/repos?per_page=100&type=public" % name)
        return [
            ("Repositories", len(repos)),
            ("Total Stars", sum(r["stargazers_count"] for r in repos)),
            ("Total Forks", sum(r["forks_count"] for r in repos)),
        ]
    owned = [r for r in gh_json("/users/%s/repos?per_page=100&type=owner" % name) if not r["fork"]]
    profile = gh_json("/users/%s" % name)[0]
    return [
        ("Public Repos", len(owned)),
        ("Total Stars", sum(r["stargazers_count"] for r in owned)),
        ("Followers", profile["followers"]),
    ]


def render(name, eyebrow, metrics, theme, out):
    c = THEMES[theme]
    lines = [
        '<svg width="%d" height="%d" viewBox="0 0 %d %d" fill="none" '
        'xmlns="http://www.w3.org/2000/svg" role="img">' % (WIDTH, HEIGHT, WIDTH, HEIGHT),
        "  <style>",
        "    .title { font: 600 17px %s; fill: %s; }" % (FONT, c["title"]),
        "    .eyebrow { font: 600 10px %s; fill: %s; letter-spacing: 1.6px; }" % (FONT, c["muted"]),
        "    .value { font: 700 24px %s; fill: %s; }" % (FONT, c["accent"]),
        "    .label { font: 500 10px %s; fill: %s; letter-spacing: 1.1px; }" % (FONT, c["muted"]),
        "  </style>",
        '  <rect x="0.5" y="0.5" width="%d" height="%d" rx="12" fill="%s" stroke="%s"/>'
        % (WIDTH - 1, HEIGHT - 1, c["bg"], c["border"]),
        '  <text class="title" x="%d" y="42">%s</text>' % (PAD, name),
        '  <text class="eyebrow" x="%d" y="42" text-anchor="end">%s</text>' % (WIDTH - PAD, eyebrow),
        '  <line x1="%d" y1="60" x2="%d" y2="60" stroke="%s"/>' % (PAD, WIDTH - PAD, c["divider"]),
    ]
    for index, (label, value) in enumerate(metrics):
        center = (COLUMNS[index] + COLUMNS[index + 1]) / 2.0
        lines.append('  <text class="value" x="%.1f" y="101" text-anchor="middle">%s</text>'
                     % (center, compact(value)))
        lines.append('  <text class="label" x="%.1f" y="123" text-anchor="middle">%s</text>'
                     % (center, label.upper()))
        if index:
            lines.append('  <line x1="%.1f" y1="78" x2="%.1f" y2="126" stroke="%s"/>'
                         % (COLUMNS[index], COLUMNS[index], c["divider"]))
    lines.append("</svg>")
    with open(out, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("user", "org"), required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--theme", default="light", choices=sorted(THEMES))
    parser.add_argument("--eyebrow", default=None)
    args = parser.parse_args()
    eyebrow = args.eyebrow or ("ORGANIZATION" if args.kind == "org" else "GITHUB STATS")
    render(args.name, eyebrow, metrics_for(args.kind, args.name), args.theme, args.out)


if __name__ == "__main__":
    main()
