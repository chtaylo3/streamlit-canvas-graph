from __future__ import annotations

import fnmatch
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Self

import httpx


class GitHubError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Repository:
    repo_id: int
    full_name: str
    name: str
    owner: str
    private: bool
    archived: bool
    default_branch: str
    size_kb: int
    html_url: str


class GitHubClient:
    def __init__(self, token: str, *, timeout: float = 30) -> None:
        if not token:
            raise GitHubError("A GitHub token is required")
        self.client = httpx.Client(
            base_url="https://api.github.com",
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "streamlit-canvas-graph",
            },
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.client.close()

    def get(self, path: str, **kwargs: Any) -> Any:
        response = self.client.get(path, **kwargs)
        if response.is_error:
            raise GitHubError(
                f"GitHub API request failed ({response.status_code}) for {path}"
            )
        return response.json()

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        response = self.client.post(path, json=payload)
        if response.is_error:
            raise GitHubError(
                f"GitHub API request failed ({response.status_code}) for {path}"
            )
        return response.json()

    def put(self, path: str, payload: dict[str, Any]) -> None:
        response = self.client.put(path, json=payload)
        if response.is_error:
            raise GitHubError(
                f"GitHub API request failed ({response.status_code}) for {path}"
            )

    def delete(self, path: str) -> None:
        response = self.client.delete(path)
        if response.is_error:
            raise GitHubError(
                f"GitHub API request failed ({response.status_code}) for {path}"
            )

    def authenticated_user(self) -> dict[str, Any]:
        return self.get("/user")

    def owned_repositories(self, owner: str) -> list[Repository]:
        results: list[Repository] = []
        page = 1
        while True:
            rows = self.get(
                "/user/repos",
                params={
                    "visibility": "all",
                    "affiliation": "owner",
                    "per_page": 100,
                    "page": page,
                    "sort": "full_name",
                },
            )
            if not rows:
                break
            for row in rows:
                if (
                    row["owner"]["login"].casefold() == owner.casefold()
                    and not row["archived"]
                ):
                    results.append(
                        Repository(
                            row["id"],
                            row["full_name"],
                            row["name"],
                            row["owner"]["login"],
                            row["private"],
                            row["archived"],
                            row["default_branch"],
                            row["size"],
                            row["html_url"],
                        )
                    )
            page += 1
        return results

    def repository(self, full_name: str) -> dict[str, Any]:
        return self.get(f"/repos/{full_name}")

    def license(self, full_name: str) -> dict[str, Any]:
        return self.get(f"/repos/{full_name}/license")

    def tree(self, full_name: str, ref: str) -> list[dict[str, Any]]:
        payload = self.get(
            f"/repos/{full_name}/git/trees/{ref}", params={"recursive": "1"}
        )
        return payload.get("tree", [])

    def content(self, full_name: str, path: str, ref: str) -> str:
        response = self.client.get(
            f"/repos/{full_name}/contents/{path}",
            params={"ref": ref},
            headers={"Accept": "application/vnd.github.raw+json"},
        )
        if response.is_error:
            raise GitHubError(
                f"Unable to read {full_name}/{path} ({response.status_code})"
            )
        return response.text

    def sbom(self, full_name: str) -> dict[str, Any]:
        return self.get(f"/repos/{full_name}/dependency-graph/sbom").get("sbom", {})

    def create_private_repository(self, name: str, description: str) -> dict[str, Any]:
        return self.post(
            "/user/repos",
            {
                "name": name,
                "description": description,
                "private": True,
                "auto_init": False,
                "has_issues": False,
                "has_projects": False,
                "has_wiki": False,
            },
        )

    def disable_actions(self, full_name: str) -> None:
        self.put(f"/repos/{full_name}/actions/permissions", {"enabled": False})

    def delete_repository(self, full_name: str) -> None:
        self.delete(f"/repos/{full_name}")


def matching_paths(
    tree: Iterable[dict[str, Any]], patterns: Iterable[str]
) -> list[str]:
    paths = [row["path"] for row in tree if row.get("type") == "blob"]
    matches: set[str] = set()
    for path in paths:
        if any(
            fnmatch.fnmatch(path, pattern)
            or fnmatch.fnmatch(path.split("/")[-1], pattern)
            for pattern in patterns
        ):
            matches.add(path)
    return sorted(matches)
