#!/usr/bin/env python3

import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any


OWNER = "rafalmasiarek"
README_PATH = Path("README.md")

START_MARKER = "<!-- projects:start -->"
END_MARKER = "<!-- projects:end -->"

EXCLUDED_REPOS = {
    "rafalmasiarek",
    "rafalmasiarek.github.io",
    "cdn.masiarek.dev",
    "iledopolandrockfestival.pl"
}

CATEGORY_ORDER = [
    "Infrastructure",
    "Ansible",
    "Docker",
    "PHP",
    "JavaScript",
    "Python",
    "Go",
    "Tools",
    "Other",
]

CATEGORY_RULES = [
    {
        "category": "Infrastructure",
        "any": [
            {"name": r"^(terraform-|opentofu-|tofu-|tf-)"},
            {"topic": r"^(terraform|opentofu|tofu)$"},
        ],
    },
    {
        "category": "Ansible",
        "any": [
            {"name": r"^ansible-"},
            {"topic": r"^ansible$"},
        ],
    },
    {
        "category": "Docker",
        "any": [
            {"name": r"^docker-"},
            {"topic": r"^(docker|container|containers)$"},
        ],
    },
    {
        "category": "PHP",
        "any": [
            {"name": r"^php-"},
            {"topic": r"^php$"},
            {"language": r"^PHP$"},
        ],
    },
    {
        "category": "JavaScript",
        "any": [
            {"name": r"^js-"},
            {"topic": r"^(javascript|js|typescript|ts|node|npm)$"},
            {"language": r"^(JavaScript|TypeScript)$"},
        ],
    },
    {
        "category": "Python",
        "any": [
            {"name": r"^py-"},
            {"topic": r"^(python|py)$"},
            {"language": r"^Python$"},
        ],
    },
    {
        "category": "Go",
        "any": [
            {"name": r"^go-"},
            {"topic": r"^(go|golang)$"},
            {"language": r"^Go$"},
        ],
    },
    {
        "category": "Tools",
        "any": [
            {"topic": r"^(cli|tool|tools|automation|utility|utilities)$"},
            {"language": r"^(Shell|Makefile)$"},
        ],
    },
]


def github_token() -> str | None:
    return os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")


def github_api(path: str) -> Any:
    token = github_token()

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "rafalmasiarek-projects-generator",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(
        f"https://api.github.com{path}",
        headers=headers,
    )

    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GitHub API request failed: {path} "
            f"status={error.code} body={body}"
        ) from error


def fetch_public_repos() -> list[dict[str, Any]]:
    repos: list[dict[str, Any]] = []
    page = 1

    while True:
        batch = github_api(
            f"/users/{OWNER}/repos"
            f"?type=owner"
            f"&sort=updated"
            f"&direction=desc"
            f"&per_page=100"
            f"&page={page}"
        )

        if not batch:
            break

        repos.extend(batch)
        page += 1

    return repos


def fetch_topics(repo_name: str) -> list[str]:
    data = github_api(f"/repos/{OWNER}/{repo_name}/topics")
    return data.get("names", [])


def should_include(repo: dict[str, Any]) -> bool:
    name = repo.get("name", "")

    if name in EXCLUDED_REPOS:
        return False

    if repo.get("fork"):
        return False

    if repo.get("archived"):
        return False

    if repo.get("private"):
        return False

    return True


def field_matches(repo: dict[str, Any], topics: list[str], condition: dict[str, str]) -> bool:
    for field, pattern in condition.items():
        regex = re.compile(pattern, re.IGNORECASE)

        if field == "name":
            return bool(regex.search(repo.get("name", "")))

        if field == "language":
            return bool(regex.search(repo.get("language") or ""))

        if field == "topic":
            return any(regex.search(topic) for topic in topics)

        raise ValueError(f"Unsupported rule field: {field}")

    return False


def rule_matches(repo: dict[str, Any], topics: list[str], rule: dict[str, Any]) -> bool:
    any_conditions = rule.get("any", [])
    all_conditions = rule.get("all", [])

    if any_conditions and not any(
        field_matches(repo, topics, condition)
        for condition in any_conditions
    ):
        return False

    if all_conditions and not all(
        field_matches(repo, topics, condition)
        for condition in all_conditions
    ):
        return False

    return True


def categorize(repo: dict[str, Any], topics: list[str]) -> str:
    for rule in CATEGORY_RULES:
        if rule_matches(repo, topics, rule):
            return rule["category"]

    return "Other"


def repo_link(repo_name: str) -> str:
    return f"[{repo_name}](https://github.com/{OWNER}/{repo_name})"

def build_projects_section(groups: dict[str, list[str]]) -> str:
    lines = [
        START_MARKER,
        '<h2 class="projects-heading"><span aria-hidden="true">&gt;</span> My Projects</h2>',
        "",
        "You can find all my projects [here](https://masiarek.pl/projects).",
        "",
    ]

    for category in CATEGORY_ORDER:
        repos = groups.get(category, [])

        if not repos:
            continue

        links = " · ".join(
            repo_link(repo_name)
            for repo_name in sorted(repos, key=str.lower)
        )

        lines.extend(
            [
                f"**{category}:** {links}",
                "",
            ]
        )

    lines.append(END_MARKER)

    return "\n".join(lines)

def replace_projects_section(readme: str, section: str) -> str:
    if START_MARKER not in readme or END_MARKER not in readme:
        return readme.rstrip() + "\n\n" + section + "\n"

    pattern = re.compile(
        re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER),
        re.DOTALL,
    )

    return pattern.sub(section, readme).rstrip() + "\n"


def main() -> int:
    if not README_PATH.exists():
        print(f"README not found: {README_PATH}", file=sys.stderr)
        return 1

    repos = fetch_public_repos()
    groups: dict[str, list[str]] = defaultdict(list)

    for repo in repos:
        if not should_include(repo):
            continue

        repo_name = repo["name"]
        topics = fetch_topics(repo_name)
        category = categorize(repo, topics)

        groups[category].append(repo_name)

    section = build_projects_section(groups)

    readme = README_PATH.read_text(encoding="utf-8")
    updated = replace_projects_section(readme, section)

    README_PATH.write_text(updated, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
