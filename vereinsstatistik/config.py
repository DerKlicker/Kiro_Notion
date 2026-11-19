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

# Verzeichnis für config.yaml und .env. Standardmäßig die Projektwurzel (lokale
# Entwicklung). In der TrueNAS-App-Variante ohne Shell wird ein persistentes
# Host-Verzeichnis per Umgebungsvariable VEREINSSTATISTIK_CONFIG_DIR gesetzt,
# in das die Web-UI die config.yaml selbst anlegt. Abwärtskompatibel: ist die
# Variable nicht gesetzt oder leer, bleibt alles wie bisher.
_CONFIG_DIR_ENV = "VEREINSSTATISTIK_CONFIG_DIR"


def _config_dir() -> Path:
    """Das Verzeichnis für config.yaml/.env bestimmen (Env-Variable oder ROOT)."""
    override = os.environ.get(_CONFIG_DIR_ENV)
    if override:
        return Path(override)
    return ROOT


CONFIG_DIR = _config_dir()
CONFIG_PATH = CONFIG_DIR / "config.yaml"
ENV_PATH = CONFIG_DIR / ".env"

# Referenz-Vorlage im Image/Repo, aus der beim ersten Start eine fehlende
# config.yaml erzeugt wird (siehe ensure_config_initialized).
EXAMPLE_CONFIG_PATH = ROOT / "config.example.yaml"

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


def ensure_config_initialized(
    config_path: Path = CONFIG_PATH,
    example_path: Path = EXAMPLE_CONFIG_PATH,
) -> bool:
    """Beim App-Start eine fehlende config.yaml aus der Vorlage erzeugen.

    Gedacht für die reine TrueNAS-App-Variante ohne Shell: Dort existiert beim
    ersten Start keine config.yaml, weil der Nutzer nie eine Konsole öffnet. Ist
    an CONFIG_PATH noch keine Datei vorhanden, wird sie aus
    ``config.example.yaml`` kopiert; die Web-UI befüllt sie anschließend.

    Idempotent und sicher: Eine bereits existierende config.yaml wird NIEMALS
    überschrieben. Fehlt auch die Vorlage, wird eine minimale Default-Struktur
    geschrieben, damit die Web-UI in jedem Fall starten kann. Das Zielverzeichnis
    wird bei Bedarf angelegt.

    Rückgabe: True, wenn eine Datei neu erzeugt wurde, sonst False.
    """
    if config_path.exists():
        return False

    config_path.parent.mkdir(parents=True, exist_ok=True)

    if example_path.exists():
        inhalt = example_path.read_text(encoding="utf-8")
    else:
        inhalt = yaml.safe_dump(
            _default_config_dict(), sort_keys=False, allow_unicode=True
        )

    config_path.write_text(inhalt, encoding="utf-8")
    return True


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
