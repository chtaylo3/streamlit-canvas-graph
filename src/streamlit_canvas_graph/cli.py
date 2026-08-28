from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from .database import create_demo_dataset
from .github_client import GitHubClient
from .ingestion import ingest_repositories
from .provisioning import (
    active_provisioned,
    cleanup,
    load_catalog,
    preflight,
    provision,
)
from .settings import get_config

console = Console()
config = get_config()
ingest_app = typer.Typer(help="Collect repository dependency snapshots.")
provision_app = typer.Typer(help="Manage private test repository copies.")
app = typer.Typer(help="GitHub-backed dependency explorer utilities.")
app.add_typer(ingest_app, name="ingest")
app.add_typer(provision_app, name="provision")


def _token(name: str) -> str:
    try:
        return config.require_secret(name)
    except RuntimeError as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command("demo")
def demo(
    output: Annotated[
        Path, typer.Option(help="Local gitignored data directory.")
    ] = config.data_dir,
    overwrite: Annotated[
        bool, typer.Option(help="Replace an existing demo database.")
    ] = False,
) -> None:
    path = create_demo_dataset(output, overwrite=overwrite)
    console.print(f"Created demo dataset: [bold]{path}[/bold]")


@ingest_app.command("github")
def ingest_github(
    output: Annotated[
        Path, typer.Option(help="Local gitignored data directory.")
    ] = config.github_output_dir,
    repositories: Annotated[
        list[str] | None,
        typer.Option(
            "--repo", help="Repository full name; repeat for noninteractive selection."
        ),
    ] = None,
    yes: Annotated[
        bool, typer.Option("--yes", help="Confirm a selection supplied through --repo.")
    ] = False,
) -> None:
    token = _token("github_read_token")
    with GitHubClient(token) as client:
        account = client.authenticated_user()
        available = client.owned_repositories(account["login"])
        by_name = {
            repository.full_name.casefold(): repository for repository in available
        }
        if repositories:
            missing = [name for name in repositories if name.casefold() not in by_name]
            if missing:
                raise typer.BadParameter(
                    f"Not owned by authenticated account or inaccessible: {', '.join(missing)}"
                )
            selected = [by_name[name.casefold()] for name in repositories]
            if not yes and not typer.confirm(
                f"Ingest {len(selected)} selected repositories as {account['login']}?"
            ):
                raise typer.Abort()
        else:
            _repository_table(available)
            raw = typer.prompt("Select repository numbers (comma-separated)")
            try:
                indexes = {int(value.strip()) - 1 for value in raw.split(",")}
                selected = [available[index] for index in sorted(indexes)]
            except (ValueError, IndexError) as exc:
                raise typer.BadParameter(
                    "Selection must contain valid comma-separated repository numbers"
                ) from exc
            if not selected or not typer.confirm(
                f"Ingest {len(selected)} repositories as {account['login']}?"
            ):
                raise typer.Abort()
        path, snapshot = ingest_repositories(client, account, selected, output)
    console.print(f"Snapshot [bold]{snapshot}[/bold] written to {path}")


@provision_app.command("create")
def provision_create(
    prefix: Annotated[
        str, typer.Option(help="Prefix for generated destination repository names.")
    ] = config.provisioning_prefix,
    catalog: Annotated[
        Path, typer.Option(help="Curated source catalog.")
    ] = config.repository_catalog,
    manifest: Annotated[
        Path, typer.Option(help="Gitignored provisioning manifest.")
    ] = config.provisioning_manifest,
    sources: Annotated[
        list[str] | None,
        typer.Option(
            "--source", help="Source full name; repeat to override catalog defaults."
        ),
    ] = None,
    yes: Annotated[
        bool, typer.Option("--yes", help="Accept the displayed creation preview.")
    ] = False,
) -> None:
    token = _token("github_provision_token")
    entries = load_catalog(catalog)
    if sources:
        requested = {source.casefold() for source in sources}
        selected = [
            entry for entry in entries if entry.full_name.casefold() in requested
        ]
        missing = requested - {entry.full_name.casefold() for entry in selected}
        if missing:
            raise typer.BadParameter(
                f"Sources are not in the curated catalog: {', '.join(sorted(missing))}"
            )
    else:
        selected = [entry for entry in entries if entry.default_selected]
    with GitHubClient(token) as client:
        account = client.authenticated_user()
        checks = [preflight(client, entry) for entry in selected]
        _preflight_table(checks, account["login"], prefix)
        unavailable = [check for check in checks if not check.available]
        if unavailable:
            console.print(
                f"[red]{len(unavailable)} sources failed preflight. No repositories were created.[/red]"
            )
            raise typer.Exit(2)
        if not yes and not typer.confirm(
            f"Create {len(checks)} private repositories under {account['login']}?"
        ):
            raise typer.Abort()
        for check in checks:
            record = provision(client, token, account["login"], check, prefix, manifest)
            console.print(f"Created [bold]{record['destination_full_name']}[/bold]")


@provision_app.command("cleanup")
def provision_cleanup(
    manifest: Annotated[
        Path, typer.Option(help="Gitignored provisioning manifest.")
    ] = config.provisioning_manifest,
    repositories: Annotated[
        list[str] | None,
        typer.Option(
            "--repo", help="Provisioned full name; repeat to select a subset."
        ),
    ] = None,
    yes: Annotated[
        bool, typer.Option("--yes", help="Accept the displayed deletion preview.")
    ] = False,
) -> None:
    token = _token("github_provision_token")
    active = active_provisioned(manifest)
    selected = {row["destination_full_name"] for row in active}
    if repositories:
        requested = set(repositories)
        if not requested <= selected:
            raise typer.BadParameter(
                "Every --repo must be active in the local provisioning manifest"
            )
        selected = requested
    if not selected:
        console.print("No active provisioned repositories to remove.")
        return
    console.print(
        "[bold red]The following private repositories will be permanently deleted:[/bold red]"
    )
    for full_name in sorted(selected):
        console.print(f"  • {full_name}")
    if not yes and not typer.confirm(
        f"Permanently delete {len(selected)} repositories?"
    ):
        raise typer.Abort()
    with GitHubClient(token) as client:
        account = client.authenticated_user()
        if any(
            not name.casefold().startswith(f"{account['login'].casefold()}/")
            for name in selected
        ):
            raise typer.BadParameter(
                "Manifest contains a repository outside the authenticated account"
            )
        removed = cleanup(client, manifest, selected)
    console.print(f"Removed {len(removed)} repositories.")


def _repository_table(repositories: list[object]) -> None:
    table = Table("#", "Repository", "Visibility", "Size (MB)")
    for index, repository in enumerate(repositories, 1):
        table.add_row(
            str(index),
            repository.full_name,
            "private" if repository.private else "public",
            f"{repository.size_kb / 1024:.1f}",
        )
    console.print(table)


def _preflight_table(checks: list[object], owner: str, prefix: str) -> None:
    table = Table(
        "Source",
        "Ecosystem",
        "Status",
        "Size (MB)",
        "License",
        "Manifests",
        "Destination owner",
    )
    for check in checks:
        table.add_row(
            check.entry.full_name,
            check.entry.ecosystem,
            "ready" if check.available else check.reason or "unavailable",
            f"{(check.size_kb or 0) / 1024:.1f}",
            check.detected_license or "unknown",
            str(len(check.matching_manifests)),
            owner,
        )
    console.print(table)
    console.print(
        f"Destination prefix: [bold]{prefix}[/bold]; all created repositories will be private."
    )


if __name__ == "__main__":
    app()
