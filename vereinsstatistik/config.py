"""Konfiguration laden, validieren und speichern.

Die Konfiguration kommt aus zwei Quellen:
  * ``config.yaml``  — Datenbank-/Feld-Mapping und Auswertungs-Optionen.
  * ``.env`` / Umgebung — Secrets (NOTION_TOKEN, PG_PASSWORD).

Das Mapping ist bewusst datengetrieben: Jede Datenbank nennt ihre
Notion-Property-Namen in ``fields``. Wird eine Spalte in Notion umbenannt,
muss nur der Wert in der YAML angepasst werden — nirgends im Code.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Projektwurzel = eine Ebene über diesem Package.
ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
ENV_PATH = ROOT / ".env"

DEFAULT_API_VERSION = "2025-09-03"


class DatabaseConfig(BaseModel):
    """Eine der drei Notion-Datenbanken."""

    database_id: str = ""
    data_source_id: str = ""
    # interner Name -> echter Notion-Property-Name
    fields: Dict[str, str] = Field(default_factory=dict)

    def is_configured(self) -> bool:
        return bool(self.database_id or self.data_source_id)


class NotionConfig(BaseModel):
    api_version: str = DEFAULT_API_VERSION


class AnalysisConfig(BaseModel):
    only_active_members: bool = False
    bundesland: str = ""


class PostgresConfig(BaseModel):
    enabled: bool = False
    host: str = "localhost"
    port: int = 5432
    database: str = "vereinsstatistik"
    user: str = "verein"
    schema_: str = Field(default="public", alias="schema")

    model_config = {"populate_by_name": True}


class Config(BaseModel):
    notion: NotionConfig = Field(default_factory=NotionConfig)
    databases: Dict[str, DatabaseConfig] = Field(default_factory=dict)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    postgres: PostgresConfig = Field(default_factory=PostgresConfig)

    # ---- Secrets (nicht aus YAML, sondern Umgebung) -----------------------

    @property
    def notion_token(self) -> Optional[str]:
        return os.environ.get("NOTION_TOKEN") or None

    @property
    def pg_password(self) -> Optional[str]:
        return os.environ.get("PG_PASSWORD") or None

    # ---- Komfort ----------------------------------------------------------

    def db(self, key: str) -> DatabaseConfig:
        """Datenbank-Konfig anhand internen Schlüssels (mitglieder/…)."""
        if key not in self.databases:
            raise KeyError(
                f"Datenbank '{key}' ist nicht konfiguriert. "
                f"Verfügbar: {list(self.databases)}"
            )
        return self.databases[key]


def _default_config_dict() -> Dict[str, Any]:
    """Minimale, leere Struktur, falls noch keine config.yaml existiert."""
    return {
        "notion": {"api_version": DEFAULT_API_VERSION},
        "databases": {
            "mitglieder": {"database_id": "", "data_source_id": "", "fields": {}},
            "gruppenstunden": {"database_id": "", "data_source_id": "", "fields": {}},
            "lager": {"database_id": "", "data_source_id": "", "fields": {}},
        },
        "analysis": {"only_active_members": False, "bundesland": ""},
        "postgres": {
            "enabled": False,
            "host": "localhost",
            "port": 5432,
            "database": "vereinsstatistik",
            "user": "verein",
            "schema": "public",
        },
    }


def load_config(path: Path = CONFIG_PATH, load_env: bool = True) -> Config:
    """config.yaml + .env laden. Fehlt die YAML, wird eine leere Struktur genutzt."""
    if load_env and ENV_PATH.exists():
        load_dotenv(ENV_PATH)

    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    else:
        raw = _default_config_dict()

    return Config.model_validate(raw)


def save_config(cfg: Config, path: Path = CONFIG_PATH) -> None:
    """Konfiguration als YAML speichern (ohne Secrets)."""
    data = cfg.model_dump(by_alias=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def save_token(token: str, path: Path = ENV_PATH) -> None:
    """NOTION_TOKEN in die .env schreiben/aktualisieren (andere Keys bleiben)."""
    lines: list[str] = []
    found = False
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("NOTION_TOKEN="):
                lines.append(f"NOTION_TOKEN={token}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"NOTION_TOKEN={token}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Sofort für den laufenden Prozess verfügbar machen.
    os.environ["NOTION_TOKEN"] = token
