#!/usr/bin/env python3
"""
generate_stats.py
Self-hosted, zero-dependency GitHub profile stats SVG generator.
Queries GitHub's GraphQL API and outputs deterministic, dark-mode SVG cards:
- stats.svg   (Total contributions, breakdown & 52-week activity bars)
- streak.svg  (Current streak & Longest streak with date ranges)
- langs.svg   (Top languages by code volume & percentage)
- year.svg    (Compact year contribution heatmap)
"""

import os
import sys
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GH_LOGIN = os.environ.get("GH_LOGIN", "beginnercodee")

if not GITHUB_TOKEN:
    print("Warning: GITHUB_TOKEN is not set. API calls may fail or be heavily rate-limited.", file=sys.stderr)

GRAPHQL_URL = "https://api.github.com/graphql"

def fetch_graphql(query, variables):
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": f"github-profile-generator-{GH_LOGIN}"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "errors" in data:
                print("GraphQL errors:", data["errors"], file=sys.stderr)
            return data.get("data", {})
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.read().decode('utf-8')}", file=sys.stderr)
        return {}
    except Exception as e:
        print(f"Request failed: {e}", file=sys.stderr)
        return {}

def get_stats_data(login):
    now_utc = datetime.now(timezone.utc)
    # Pin window to exactly whole UTC days (today - 364 days 00:00:00Z to today 23:59:59Z)
    today = now_utc.date()
    from_date = today - timedelta(days=364)
    from_iso = f"{from_date.isoformat()}T00:00:00Z"
    to_iso = f"{today.isoformat()}T23:59:59Z"

    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        name
        createdAt
        contributionsCollection(from: $from, to: $to) {
          totalCommitContributions
          totalIssueContributions
          totalPullRequestContributions
          totalPullRequestReviewContributions
          restrictedContributionsCount
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays {
                contributionCount
                date
                weekday
              }
            }
          }
        }
        repositories(first: 100, ownerAffiliations: OWNER, privacy: PUBLIC, isFork: false) {
          nodes {
            name
            stargazerCount
            forkCount
            languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
              edges {
                size
                node {
                  name
                  color
                }
              }
            }
          }
        }
      }
    }
    """
    return fetch_graphql(query, {"login": login, "from": from_iso, "to": to_iso})

def calculate_streaks(weeks, today):
    all_days = []
    for w in weeks:
        for d in w.get("contributionDays", []):
            try:
                dt = datetime.strptime(d["date"], "%Y-%m-%d").date()
                all_days.append((dt, d.get("contributionCount", 0)))
            except Exception:
                pass

    all_days.sort(key=lambda x: x[0])
    if not all_days:
        return 0, None, None, 0, None, None

    # Streak algorithm
    current_streak = 0
    curr_start = None
    curr_end = None

    longest_streak = 0
    long_start = None
    long_end = None

    temp_streak = 0
    temp_start = None
    temp_end = None

    for dt, count in all_days:
        if count > 0:
            if temp_streak == 0:
                temp_start = dt
            temp_streak += 1
            temp_end = dt
            if temp_streak > longest_streak:
                longest_streak = temp_streak
                long_start = temp_start
                long_end = temp_end
        else:
            temp_streak = 0
            temp_start = None
            temp_end = None

    # Determine current streak
    idx = len(all_days) - 1
    # Check if latest day is today or yesterday
    if idx >= 0:
        latest_date, latest_count = all_days[idx]
        prev_date, prev_count = all_days[idx - 1] if idx > 0 else (None, 0)
        
        anchor_idx = None
        if latest_count > 0:
            anchor_idx = idx
        elif latest_date == today and prev_count > 0:
            # If today has 0 contributions so far, yesterday's streak is still active
            anchor_idx = idx - 1

        if anchor_idx is not None:
            curr_end = all_days[anchor_idx][0]
            c = 0
            while anchor_idx >= 0 and all_days[anchor_idx][1] > 0:
                curr_start = all_days[anchor_idx][0]
                c += 1
                anchor_idx -= 1
            current_streak = c

    return current_streak, curr_start, curr_end, longest_streak, long_start, long_end

def generate_stats_svg(user_data, output_path="stats.svg"):
    col = user_data.get("contributionsCollection", {})
    calendar = col.get("contributionCalendar", {})
    total_contribs = calendar.get("totalContributions", 0)
    commits = col.get("totalCommitContributions", 0)
    prs = col.get("totalPullRequestContributions", 0)
    issues = col.get("totalIssueContributions", 0)
    reviews = col.get("totalPullRequestReviewContributions", 0)

    # Weekly aggregates for sparkline / columns
    weeks = calendar.get("weeks", [])
    weekly_counts = [sum(d.get("contributionCount", 0) for d in w.get("contributionDays", [])) for w in weeks]
    if len(weekly_counts) > 52:
        weekly_counts = weekly_counts[-52:]
    max_count = max(weekly_counts) if weekly_counts and max(weekly_counts) > 0 else 1

    bar_width = 7.5
    gap = 2.5
    chart_x = 24
    chart_y = 115
    chart_h = 42

    bars_svg = []
    for i, count in enumerate(weekly_counts):
        bx = chart_x + i * (bar_width + gap)
        bh = max(2.5, (count / max_count) * chart_h) if count > 0 else 2.0
        by = chart_y + (chart_h - bh)
        color = "#238636" if count > 0 else "#21262d"
        bars_svg.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_width}" height="{bh:.1f}" rx="1.5" fill="{color}" />')

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="560" height="180" viewBox="0 0 560 180" fill="none">
  <style>
    .header {{ font: 600 14px -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; fill: #58a6ff; }}
    .num {{ font: 700 24px -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; fill: #f0f6fc; }}
    .label {{ font: 400 12px -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; fill: #8b949e; }}
    .sublabel {{ font: 400 11px -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; fill: #6e7681; }}
  </style>
  <rect x="0.5" y="0.5" width="559" height="179" rx="8" fill="#0d1117" stroke="#30363d"/>
  
  <text x="24" y="32" class="header">✦ ANNUAL CONTRIBUTIONS &amp; ACTIVITY</text>
  
  <!-- Metrics -->
  <text x="24" y="66" class="num">{total_contribs:,}</text>
  <text x="24" y="84" class="label">Total in past year</text>

  <text x="175" y="66" class="num">{commits:,}</text>
  <text x="175" y="84" class="label">Commits</text>

  <text x="295" y="66" class="num">{prs:,}</text>
  <text x="295" y="84" class="label">Pull Requests</text>

  <text x="420" y="66" class="num">{issues + reviews:,}</text>
  <text x="420" y="84" class="label">Issues &amp; Reviews</text>

  <!-- 52-week activity columns -->
  {''.join(bars_svg)}
  
  <text x="24" y="170" class="sublabel">52-week activity histogram</text>
  <text x="536" y="170" text-anchor="end" class="sublabel">Today</text>
</svg>"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg)

def generate_streak_svg(user_data, today, output_path="streak.svg"):
    calendar = user_data.get("contributionsCollection", {}).get("contributionCalendar", {})
    weeks = calendar.get("weeks", [])
    curr, c_start, c_end, longest, l_start, l_end = calculate_streaks(weeks, today)

    c_range = f"{c_start.strftime('%b %d')} - {c_end.strftime('%b %d')}" if c_start and c_end else "No active streak"
    l_range = f"{l_start.strftime('%b %d, %Y')} - {l_end.strftime('%b %d, %Y')}" if l_start and l_end else "N/A"

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="560" height="130" viewBox="0 0 560 130" fill="none">
  <style>
    .header {{ font: 600 13px -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; fill: #ff7b72; }}
    .num {{ font: 700 26px -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; fill: #f0f6fc; }}
    .label {{ font: 500 12px -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; fill: #8b949e; }}
    .range {{ font: 400 11px -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; fill: #6e7681; }}
  </style>
  <rect x="0.5" y="0.5" width="559" height="129" rx="8" fill="#0d1117" stroke="#30363d"/>
  
  <!-- Current Streak -->
  <g transform="translate(24, 26)">
    <text x="0" y="0" class="header">🔥 CURRENT STREAK</text>
    <text x="0" y="34" class="num">{curr} <tspan font-size="15" fill="#8b949e" font-weight="normal">days</tspan></text>
    <text x="0" y="55" class="label">{c_range}</text>
  </g>

  <!-- Divider -->
  <line x1="280" y1="20" x2="280" y2="110" stroke="#21262d" stroke-width="1"/>

  <!-- Longest Streak -->
  <g transform="translate(304, 26)">
    <text x="0" y="0" class="header" fill="#d29922">⚡ LONGEST STREAK</text>
    <text x="0" y="34" class="num">{longest} <tspan font-size="15" fill="#8b949e" font-weight="normal">days</tspan></text>
    <text x="0" y="55" class="label">{l_range}</text>
  </g>
</svg>"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg)

def generate_langs_svg(user_data, output_path="langs.svg"):
    repos = user_data.get("repositories", {}).get("nodes", [])
    lang_bytes = {}
    lang_colors = {}

    for r in repos:
        for edge in r.get("languages", {}).get("edges", []):
            size = edge.get("size", 0)
            node = edge.get("node", {})
            name = node.get("name")
            color = node.get("color") or "#8b949e"
            if name:
                lang_bytes[name] = lang_bytes.get(name, 0) + size
                lang_colors[name] = color

    total_bytes = sum(lang_bytes.values())
    sorted_langs = sorted(lang_bytes.items(), key=lambda x: x[1], reverse=True)[:6]

    bar_elements = []
    legend_elements = []
    x_cursor = 24.0
    bar_width_total = 512.0

    for idx, (lang, size) in enumerate(sorted_langs):
        pct = (size / total_bytes) * 100 if total_bytes > 0 else 0
        w = (size / total_bytes) * bar_width_total if total_bytes > 0 else 0
        color = lang_colors.get(lang, "#58a6ff")
        bar_elements.append(f'<rect x="{x_cursor:.1f}" y="50" width="{w:.1f}" height="10" rx="2" fill="{color}"/>')
        x_cursor += w

        # Legend (2 rows x 3 cols)
        col_idx = idx % 3
        row_idx = idx // 3
        lx = 24 + col_idx * 175
        ly = 85 + row_idx * 26
        legend_elements.append(f"""
        <circle cx="{lx+4}" cy="{ly-4}" r="4" fill="{color}"/>
        <text x="{lx+16}" y="{ly}" class="lang-text">{lang} <tspan class="lang-pct">{pct:.1f}%</tspan></text>
        """)

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="560" height="150" viewBox="0 0 560 150" fill="none">
  <style>
    .header {{ font: 600 13px -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; fill: #58a6ff; }}
    .lang-text {{ font: 500 12px -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; fill: #f0f6fc; }}
    .lang-pct {{ font: 400 12px -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; fill: #8b949e; }}
  </style>
  <rect x="0.5" y="0.5" width="559" height="149" rx="8" fill="#0d1117" stroke="#30363d"/>
  <text x="24" y="32" class="header">TOP LANGUAGES (BY REPO BYTES)</text>
  
  <!-- Bar -->
  <rect x="24" y="50" width="512" height="10" rx="5" fill="#21262d"/>
  {''.join(bar_elements)}

  <!-- Legend -->
  {''.join(legend_elements)}
</svg>"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg)

def generate_year_svg(user_data, output_path="year.svg"):
    calendar = user_data.get("contributionsCollection", {}).get("contributionCalendar", {})
    weeks = calendar.get("weeks", [])
    
    # Grid of squares: 52 or 53 columns x 7 rows
    cell_size = 8.5
    cell_gap = 2.0
    start_x = 24
    start_y = 48

    def get_color(count):
        if count == 0:
            return "#161b22"
        elif count <= 2:
            return "#0e4429"
        elif count <= 5:
            return "#006d32"
        elif count <= 9:
            return "#26a641"
        else:
            return "#39d353"

    rects = []
    for col_idx, w in enumerate(weeks[-52:]):
        for d in w.get("contributionDays", []):
            row_idx = d.get("weekday", 0)  # 0=Sunday, 6=Saturday
            count = d.get("contributionCount", 0)
            rx = start_x + col_idx * (cell_size + cell_gap)
            ry = start_y + row_idx * (cell_size + cell_gap)
            color = get_color(count)
            rects.append(f'<rect x="{rx:.1f}" y="{ry:.1f}" width="{cell_size}" height="{cell_size}" rx="1.5" fill="{color}"/>')

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="560" height="135" viewBox="0 0 560 135" fill="none">
  <style>
    .header {{ font: 600 13px -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; fill: #3fb950; }}
    .sublabel {{ font: 400 10px -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; fill: #6e7681; }}
  </style>
  <rect x="0.5" y="0.5" width="559" height="134" rx="8" fill="#0d1117" stroke="#30363d"/>
  <text x="24" y="30" class="header">CONTRIBUTION CALENDAR (PAST 52 WEEKS)</text>
  
  {''.join(rects)}

  <g transform="translate(425, 118)">
    <text x="-30" y="8" class="sublabel">Less</text>
    <rect x="0" y="0" width="8" height="8" rx="1.5" fill="#161b22"/>
    <rect x="11" y="0" width="8" height="8" rx="1.5" fill="#0e4429"/>
    <rect x="22" y="0" width="8" height="8" rx="1.5" fill="#006d32"/>
    <rect x="33" y="0" width="8" height="8" rx="1.5" fill="#26a641"/>
    <rect x="44" y="0" width="8" height="8" rx="1.5" fill="#39d353"/>
    <text x="56" y="8" class="sublabel">More</text>
  </g>
</svg>"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg)

def get_fallback_data(login):
    now_utc = datetime.now(timezone.utc)
    today = now_utc.date()
    # Generate 52 weeks of baseline contribution data
    weeks = []
    for w in range(52):
        days = []
        for d in range(7):
            days.append({
                "date": (today - timedelta(days=(51-w)*7 + (6-d))).isoformat(),
                "contributionCount": 1 if (w + d) % 3 == 0 else (3 if (w * d) % 5 == 0 else 0),
                "weekday": d
            })
        weeks.append({"contributionDays": days})

    return {
        "user": {
            "name": login,
            "contributionsCollection": {
                "totalCommitContributions": 142,
                "totalIssueContributions": 8,
                "totalPullRequestContributions": 19,
                "totalPullRequestReviewContributions": 4,
                "restrictedContributionsCount": 0,
                "contributionCalendar": {
                    "totalContributions": 173,
                    "weeks": weeks
                }
            },
            "repositories": {
                "nodes": [
                    {"name": "repo1", "languages": {"edges": [{"size": 180000, "node": {"name": "TypeScript", "color": "#3178c6"}}]}},
                    {"name": "repo2", "languages": {"edges": [{"size": 140000, "node": {"name": "Python", "color": "#3572A5"}}]}},
                    {"name": "repo3", "languages": {"edges": [{"size": 95000, "node": {"name": "JavaScript", "color": "#f1e05a"}}]}},
                    {"name": "repo4", "languages": {"edges": [{"size": 60000, "node": {"name": "HTML", "color": "#e34c26"}}]}},
                    {"name": "repo5", "languages": {"edges": [{"size": 45000, "node": {"name": "CSS", "color": "#563d7c"}}]}}
                ]
            }
        }
    }

def main():
    print(f"Fetching GitHub activity data for @{GH_LOGIN}...")
    user = None
    if GITHUB_TOKEN:
        data = get_stats_data(GH_LOGIN)
        user = data.get("user")

    if not user:
        print("Note: Running in offline / fallback mode (provide GITHUB_TOKEN for live stats).")
        user = get_fallback_data(GH_LOGIN)["user"]

    now_utc = datetime.now(timezone.utc)
    today = now_utc.date()

    generate_stats_svg(user, "stats.svg")
    generate_streak_svg(user, today, "streak.svg")
    generate_langs_svg(user, "langs.svg")
    generate_year_svg(user, "year.svg")
    print("Successfully generated stats.svg, streak.svg, langs.svg, and year.svg.")

if __name__ == "__main__":
    main()

