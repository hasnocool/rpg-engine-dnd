"""Publisher identity, Ed25519 signatures, trust policy, capabilities, and SBOM metadata."""

from __future__ import annotations

import base64
from pydantic import BaseModel, ConfigDict, Field

from .canonical import canonical_hash


class PublisherIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    publisher_id: str
    public_key_b64: str
    display_name: str | None = None


class PackageCapabilityManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    requested: frozenset[str] = frozenset()
    required_engine_capabilities: frozenset[str] = frozenset()


class SBOMEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    version: str
    license: str | None = None
    content_hash: str | None = None


class ContentAttestation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    package_id: str
    package_version: str
    content_hash: str
    publisher_id: str
    capabilities: PackageCapabilityManifest = Field(default_factory=PackageCapabilityManifest)
    sbom: tuple[SBOMEntry, ...] = ()
    signature_b64: str

    def signed_material(self) -> bytes:
        material = self.model_dump(mode="json", exclude={"signature_b64"})
        return canonical_hash(material).encode("ascii")


class TrustPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    trusted_publishers: frozenset[str] = frozenset()
    denied_capabilities: frozenset[str] = frozenset({"arbitrary-code", "filesystem-write", "network-raw"})
    require_signature: bool = True

    def validate(self, attestation: ContentAttestation) -> None:
        if self.trusted_publishers and attestation.publisher_id not in self.trusted_publishers:
            raise ValueError("publisher is not trusted")
        denied = self.denied_capabilities.intersection(attestation.capabilities.requested)
        if denied:
            raise ValueError(f"package requests denied capabilities: {sorted(denied)}")


class Ed25519Verifier:
    """Asymmetric package verification; imports crypto lazily to keep core startup lean."""

    @staticmethod
    def verify(identity: PublisherIdentity, attestation: ContentAttestation) -> bool:
        if identity.publisher_id != attestation.publisher_id:
            return False
        try:
            from cryptography.exceptions import InvalidSignature
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        except ImportError as exc:  # pragma: no cover - packaging environment guard
            raise RuntimeError("cryptography is required for Ed25519 verification") from exc
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(identity.public_key_b64))
        try:
            key.verify(base64.b64decode(attestation.signature_b64), attestation.signed_material())
        except (InvalidSignature, ValueError):
            return False
        return True
