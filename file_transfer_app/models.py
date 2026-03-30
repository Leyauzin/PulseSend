from dataclasses import dataclass
from pathlib import Path
from threading import Event

from .config import DEFAULT_PORT


@dataclass(slots=True)
class Contact:
    name: str
    ip: str
    port: int = DEFAULT_PORT
    ipv6: bool = False

    def to_record(self) -> dict[str, str | int | bool]:
        return {
            "ip": self.ip,
            "port": self.port,
            "ipv6": self.ipv6,
        }


@dataclass(slots=True)
class SendRequest:
    source_path: Path
    host: str
    port: int
    ipv6: bool
    chunk_size: int
    passphrase: str = ""


@dataclass(slots=True)
class ReceiveRequest:
    port: int
    allowed_ip: str = ""
    passphrase: str = ""
    save_directory: Path = Path.cwd()
    cancel_event: Event | None = None


@dataclass(slots=True)
class DiscoveredPeer:
    instance_id: str
    name: str
    ipv4: str = ""
    ipv6: str = ""
    port: int = DEFAULT_PORT
    last_seen: float = 0.0

    @property
    def label(self) -> str:
        families = []
        if self.ipv6:
            families.append("IPv6")
        if self.ipv4:
            families.append("IPv4")
        summary = " + ".join(families) if families else "sans adresse"
        return f"{self.name} - {summary} ({self.port})"

    @property
    def has_ipv4(self) -> bool:
        return bool(self.ipv4)

    @property
    def has_ipv6(self) -> bool:
        return bool(self.ipv6)

    def preferred_ip(self, prefer_ipv6: bool = True) -> str:
        if prefer_ipv6 and self.ipv6:
            return self.ipv6
        if self.ipv4:
            return self.ipv4
        return self.ipv6

    @property
    def details(self) -> str:
        parts = []
        if self.ipv6:
            parts.append(f"IPv6: {self.ipv6}")
        if self.ipv4:
            parts.append(f"IPv4: {self.ipv4}")
        details = " | ".join(parts) if parts else "Aucune adresse publiee"
        return f"{self.name} - {details} - port {self.port}"
