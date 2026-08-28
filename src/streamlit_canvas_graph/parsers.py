from __future__ import annotations

import json
import re
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import PurePosixPath


@dataclass(slots=True)
class Package:
    name: str
    version: str
    ecosystem: str
    direct: bool = False
    dependencies: list[tuple[str, str]] = field(default_factory=list)


@dataclass(slots=True)
class ParsedManifest:
    path: str
    ecosystem: str
    parser: str
    packages: list[Package]
    complete: bool = True
    warnings: list[str] = field(default_factory=list)


def parse_manifest(path: str, content: str) -> ParsedManifest:
    name = PurePosixPath(path).name
    if name in {"package-lock.json", "npm-shrinkwrap.json"}:
        return parse_package_lock(path, content)
    if name == "uv.lock" or name == "poetry.lock":
        return parse_python_lock(path, content, name.removesuffix(".lock"))
    if name.startswith("requirements") and name.endswith(".txt"):
        return parse_requirements(path, content)
    if name == "packages.lock.json":
        return parse_nuget_lock(path, content)
    if name == "Directory.Packages.props" or name.endswith(
        (".csproj", ".fsproj", ".vbproj")
    ):
        return parse_nuget_xml(path, content)
    if name in {"yarn.lock", "pnpm-lock.yaml"}:
        return ParsedManifest(
            path,
            "npm",
            name,
            [],
            False,
            [
                f"{name} is recorded but requires SBOM relationships for complete resolution"
            ],
        )
    raise ValueError(f"Unsupported manifest: {path}")


def parse_package_lock(path: str, content: str) -> ParsedManifest:
    payload = json.loads(content)
    packages: list[Package] = []
    entries = payload.get("packages", {})
    root_dependencies = set(payload.get("dependencies", {}))
    root = entries.get("", {})
    root_dependencies.update(root.get("dependencies", {}))
    root_dependencies.update(root.get("devDependencies", {}))
    for location, record in entries.items():
        if not location or "version" not in record:
            continue
        name = record.get("name") or location.rsplit("node_modules/", 1)[-1]
        dependencies = [
            (dep_name, str(spec))
            for dep_name, spec in record.get("dependencies", {}).items()
        ]
        packages.append(
            Package(
                name,
                str(record["version"]),
                "npm",
                name in root_dependencies,
                dependencies,
            )
        )
    if not packages:
        for name, record in payload.get("dependencies", {}).items():
            if isinstance(record, dict) and record.get("version"):
                packages.append(Package(name, str(record["version"]), "npm", True))
    return ParsedManifest(
        path,
        "npm",
        "package-lock",
        packages,
        bool(packages),
        [] if packages else ["No resolved packages found"],
    )


def parse_python_lock(path: str, content: str, parser: str) -> ParsedManifest:
    payload = tomllib.loads(content)
    packages: list[Package] = []
    for record in payload.get("package", []):
        name, version = record.get("name"), record.get("version")
        if not name or not version:
            continue
        dependencies: list[tuple[str, str]] = []
        for dependency in record.get("dependencies", []):
            if isinstance(dependency, str):
                dependencies.append((dependency, ""))
            elif isinstance(dependency, dict) and dependency.get("name"):
                dependencies.append(
                    (dependency["name"], str(dependency.get("version", "")))
                )
        packages.append(
            Package(
                name,
                str(version),
                "PyPI",
                bool(record.get("source", {}).get("editable")),
                dependencies,
            )
        )
    return ParsedManifest(
        path,
        "PyPI",
        parser,
        packages,
        bool(packages),
        [] if packages else ["No resolved packages found"],
    )


REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9_.-]+)(?:\[[^]]+\])?\s*==\s*([^;\s]+)")


def parse_requirements(path: str, content: str) -> ParsedManifest:
    packages = [
        Package(match.group(1), match.group(2), "PyPI", True)
        for line in content.splitlines()
        if (match := REQUIREMENT.match(line))
    ]
    return ParsedManifest(
        path,
        "PyPI",
        "requirements",
        packages,
        False,
        ["requirements files do not encode parent-child relationships"],
    )


def parse_nuget_lock(path: str, content: str) -> ParsedManifest:
    payload = json.loads(content)
    merged: dict[tuple[str, str], Package] = {}
    for framework in payload.get("dependencies", {}).values():
        for name, record in framework.items():
            if not isinstance(record, dict):
                continue
            version = str(
                record.get("resolved") or record.get("requested") or ""
            ).strip("[]() ")
            if not version:
                continue
            key = (name.casefold(), version)
            dependencies = [
                (dep_name, str(spec).strip("[]() "))
                for dep_name, spec in record.get("dependencies", {}).items()
            ]
            merged[key] = Package(
                name,
                version,
                "NuGet",
                record.get("type") in {"Direct", "Project"},
                dependencies,
            )
    packages = list(merged.values())
    return ParsedManifest(
        path,
        "NuGet",
        "packages-lock",
        packages,
        bool(packages),
        [] if packages else ["No resolved packages found"],
    )


def parse_nuget_xml(path: str, content: str) -> ParsedManifest:
    root = ET.fromstring(content)
    packages: list[Package] = []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag not in {"PackageReference", "PackageVersion"}:
            continue
        name = element.attrib.get("Include") or element.attrib.get("Update")
        version = element.attrib.get("Version") or element.findtext("Version")
        if name and version and not version.startswith("$("):
            packages.append(Package(name, version, "NuGet", True))
    return ParsedManifest(
        path,
        "NuGet",
        "msbuild",
        packages,
        False,
        [
            "MSBuild manifests contain direct requirements; use lockfile or SBOM for transitives"
        ],
    )
