import json
from pathlib import Path

from file_transfer_app.models import Contact


class ContactStore:
    def __init__(self, storage_path: Path):
        self.storage_path = storage_path

    def list_contacts(self) -> list[Contact]:
        data = self._read_raw()
        contacts: list[Contact] = []

        for name in sorted(data):
            record = data.get(name, {})
            contacts.append(
                Contact(
                    name=name,
                    ip=str(record.get("ip", "")),
                    port=self._safe_port(record.get("port")),
                    ipv6=bool(record.get("ipv6", False)),
                )
            )

        return contacts

    def list_names(self) -> list[str]:
        return [contact.name for contact in self.list_contacts()]

    def get_contact(self, name: str) -> Contact | None:
        for contact in self.list_contacts():
            if contact.name == name:
                return contact
        return None

    def save_contact(self, contact: Contact) -> None:
        data = self._read_raw()
        data[contact.name] = contact.to_record()
        self._write_raw(data)

    def delete_contact(self, name: str) -> bool:
        data = self._read_raw()
        removed = data.pop(name, None) is not None
        if removed:
            self._write_raw(data)
        return removed

    def _read_raw(self) -> dict[str, dict]:
        if not self.storage_path.exists():
            return {}

        try:
            return json.loads(self.storage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_raw(self, data: dict[str, dict]) -> None:
        self.storage_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @staticmethod
    def _safe_port(value: object) -> int:
        try:
            port = int(value)
        except (TypeError, ValueError):
            return 5001

        return port if 1 <= port <= 65535 else 5001
