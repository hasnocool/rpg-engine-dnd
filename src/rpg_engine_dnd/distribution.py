"""v2.5 semantic-versioned content dependency resolution, signing, locks, and registry."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
from dataclasses import dataclass
from functools import total_ordering

from pydantic import BaseModel, ConfigDict, Field

from .canonical import canonical_hash, canonical_json


_SEMVER = re.compile(r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)(?:-(?P<pre>[0-9A-Za-z.-]+))?$")


@total_ordering
@dataclass(frozen=True, slots=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: str = ""

    @classmethod
    def parse(cls, value: str) -> "SemVer":
        match = _SEMVER.fullmatch(value)
        if match is None:
            raise ValueError(f"invalid semantic version: {value}")
        return cls(int(match["major"]), int(match["minor"]), int(match["patch"]), match["pre"] or "")

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        return base if not self.prerelease else f"{base}-{self.prerelease}"

    @staticmethod
    def _prerelease_parts(value: str) -> tuple[tuple[int, int | str], ...]:
        if not value:
            return ()
        parts: list[tuple[int, int | str]] = []
        for identifier in value.split("."):
            if identifier.isdigit():
                parts.append((0, int(identifier)))
            else:
                parts.append((1, identifier))
        return tuple(parts)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        left_core = (self.major, self.minor, self.patch)
        right_core = (other.major, other.minor, other.patch)
        if left_core != right_core:
            return left_core < right_core
        if not self.prerelease:
            return False if not other.prerelease else False
        if not other.prerelease:
            return True
        left = self._prerelease_parts(self.prerelease)
        right = self._prerelease_parts(other.prerelease)
        for lpart, rpart in zip(left, right):
            if lpart == rpart:
                continue
            if lpart[0] != rpart[0]:
                return lpart[0] < rpart[0]
            if lpart[0] == 0:
                return int(lpart[1]) < int(rpart[1])
            return str(lpart[1]) < str(rpart[1])
        return len(left) < len(right)


class VersionConstraint:
    """Small deterministic constraint evaluator supporting comma-separated comparisons."""

    def __init__(self, expression: str) -> None:
        self.expression = expression.strip() or "*"

    def allows(self, version: str) -> bool:
        if self.expression == "*":
            return True
        parsed = SemVer.parse(version)
        for raw in self.expression.split(","):
            term = raw.strip()
            operator = next((op for op in (">=", "<=", "==", ">", "<") if term.startswith(op)), None)
            if operator is None:
                target = SemVer.parse(term)
                if parsed != target:
                    return False
                continue
            target = SemVer.parse(term[len(operator):].strip())
            if operator == ">=" and not parsed >= target:
                return False
            if operator == "<=" and not parsed <= target:
                return False
            if operator == ">" and not parsed > target:
                return False
            if operator == "<" and not parsed < target:
                return False
            if operator == "==" and not parsed == target:
                return False
        return True


class PackageDependency(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    package_id: str
    constraint: str = "*"


class PackageRelease(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    package_id: str
    version: str
    engine_constraint: str = "*"
    dependencies: tuple[PackageDependency, ...] = ()
    content_hash: str
    metadata: dict[str, object] = Field(default_factory=dict)
    signature: str | None = None


class DependencyLock(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    root_package_id: str
    releases: tuple[tuple[str, str, str], ...]
    lock_hash: str


class HMACReleaseSigner:
    def __init__(self, secret: bytes) -> None:
        if len(secret) < 16:
            raise ValueError("signing secret is too short")
        self.secret = secret

    def sign(self, release: PackageRelease) -> str:
        payload = release.model_dump(mode="json", exclude={"signature"})
        return hmac.new(self.secret, canonical_json(payload).encode(), hashlib.sha256).hexdigest()

    def verify(self, release: PackageRelease) -> bool:
        return release.signature is not None and hmac.compare_digest(release.signature, self.sign(release))


class ContentDistributionRegistry:
    def __init__(self, *, engine_version: str = "3.0.0") -> None:
        self.engine_version = engine_version
        self._releases: dict[str, dict[str, PackageRelease]] = {}
        self._locks: dict[str, DependencyLock] = {}
        self._lock = asyncio.Lock()

    async def publish(self, release: PackageRelease) -> None:
        SemVer.parse(release.version)
        if not VersionConstraint(release.engine_constraint).allows(self.engine_version):
            raise ValueError("release is incompatible with engine version")
        async with self._lock:
            self._releases.setdefault(release.package_id, {})[release.version] = release

    async def _snapshot(self) -> dict[str, dict[str, PackageRelease]]:
        async with self._lock:
            return {package: dict(versions) for package, versions in self._releases.items()}

    async def resolve(self, root_package_id: str, constraint: str = "*") -> DependencyLock:
        releases = await self._snapshot()
        selected: dict[str, PackageRelease] = {}
        visiting: set[str] = set()
        order: list[str] = []

        def choose(package_id: str, wanted: str) -> PackageRelease:
            versions = releases.get(package_id, {})
            allowed = [release for release in versions.values() if VersionConstraint(wanted).allows(release.version)]
            if not allowed:
                raise ValueError(f"no compatible release for {package_id} {wanted}")
            return max(allowed, key=lambda release: SemVer.parse(release.version))

        def visit(package_id: str, wanted: str) -> None:
            if package_id in visiting:
                raise ValueError("dependency cycle detected")
            existing = selected.get(package_id)
            if existing is not None:
                if not VersionConstraint(wanted).allows(existing.version):
                    raise ValueError("dependency constraint conflict")
                return
            visiting.add(package_id)
            release = choose(package_id, wanted)
            if not VersionConstraint(release.engine_constraint).allows(self.engine_version):
                raise ValueError("dependency is incompatible with engine version")
            selected[package_id] = release
            for dependency in sorted(release.dependencies, key=lambda item: item.package_id):
                visit(dependency.package_id, dependency.constraint)
            visiting.remove(package_id)
            order.append(package_id)

        visit(root_package_id, constraint)
        rows = tuple((package, selected[package].version, selected[package].content_hash) for package in order)
        material = {"root": root_package_id, "releases": rows}
        lock = DependencyLock(root_package_id=root_package_id, releases=rows, lock_hash=canonical_hash(material))
        async with self._lock:
            self._locks[root_package_id] = lock
        return lock

    async def upgrade_plan(self, lock: DependencyLock) -> list[tuple[str, str, str]]:
        releases = await self._snapshot()
        changes: list[tuple[str, str, str]] = []
        for package_id, current_version, _ in lock.releases:
            available = releases.get(package_id, {})
            if not available:
                continue
            newest = max(available, key=SemVer.parse)
            if SemVer.parse(newest) > SemVer.parse(current_version):
                changes.append((package_id, current_version, newest))
        return changes


class PersistentDistributionRegistry(ContentDistributionRegistry):
    """Registry variant mirrored into any AsyncPersistence-compatible backend."""

    def __init__(self, store: object, *, engine_version: str = "3.0.0") -> None:
        super().__init__(engine_version=engine_version)
        self.store = store

    async def load(self) -> None:
        list_json = getattr(self.store, "list_json")
        releases = await list_json("distribution:release")
        async with self._lock:
            self._releases.clear()
            for value in releases.values():
                release = PackageRelease.model_validate(value)
                self._releases.setdefault(release.package_id, {})[release.version] = release
            locks = await list_json("distribution:lock")
            self._locks = {
                key: DependencyLock.model_validate(value)
                for key, value in locks.items()
            }

    async def publish(self, release: PackageRelease) -> None:
        await super().publish(release)
        put_json = getattr(self.store, "put_json")
        await put_json(
            "distribution:release",
            f"{release.package_id}@{release.version}",
            release.model_dump(mode="json"),
        )

    async def resolve(self, root_package_id: str, constraint: str = "*") -> DependencyLock:
        lock = await super().resolve(root_package_id, constraint)
        put_json = getattr(self.store, "put_json")
        await put_json("distribution:lock", root_package_id, lock.model_dump(mode="json"))
        return lock
