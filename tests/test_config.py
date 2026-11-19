"""Tests fürs Laden/Speichern der Konfiguration und das DB-Mapping."""
import os
from pathlib import Path

import pytest

from vereinsstatistik.config import Config, load_config, save_config


@pytest.fixture
def clean_pg_env(monkeypatch):
    """Alle PG_*-Umgebungsvariablen vor dem Test entfernen."""
    for name in ("PG_ENABLED", "PG_HOST", "PG_PORT", "PG_DATABASE", "PG_USER", "PG_SCHEMA"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_load_defaults_when_no_file(tmp_path: Path):
    cfg = load_config(path=tmp_path / "nope.yaml", load_env=False)
    assert set(cfg.databases) == {"mitglieder", "gruppenstunden", "lager"}
    assert cfg.postgres.schema_ == "public"


def test_roundtrip_save_load(tmp_path: Path):
    cfg = load_config(path=tmp_path / "nope.yaml", load_env=False)
    cfg.databases["mitglieder"].database_id = "db-123"
    cfg.databases["mitglieder"].fields = {"name": "Name", "eintritt": "Eintrittsdatum"}
    cfg.analysis.bundesland = "BW"

    out = tmp_path / "config.yaml"
    save_config(cfg, path=out)
    assert out.exists()

    reloaded = load_config(path=out, load_env=False)
    assert reloaded.databases["mitglieder"].database_id == "db-123"
    assert reloaded.databases["mitglieder"].fields["eintritt"] == "Eintrittsdatum"
    assert reloaded.analysis.bundesland == "BW"
    # 'schema' alias muss beim Dump erhalten bleiben
    assert reloaded.postgres.schema_ == "public"


def test_db_lookup_raises_for_unknown():
    cfg = Config()
    try:
        cfg.db("gibtsnicht")
        assert False, "sollte KeyError werfen"
    except KeyError:
        pass


def test_is_configured():
    cfg = load_config(load_env=False, path=Path("/nonexistent.yaml"))
    assert cfg.databases["mitglieder"].is_configured() is False
    cfg.databases["mitglieder"].database_id = "x"
    assert cfg.databases["mitglieder"].is_configured() is True


# ---------------------------------------------------------------------------
# PostgreSQL-Einstellungen per Umgebungsvariable (Vorrang vor config.yaml)
# ---------------------------------------------------------------------------

def test_pg_env_overrides_aktivieren(tmp_path: Path, clean_pg_env):
    """PG_ENABLED/PG_HOST überschreiben die config.yaml-Werte."""
    cfg_datei = tmp_path / "config.yaml"
    cfg_datei.write_text(
        "postgres:\n  enabled: false\n  host: localhost\n  port: 5432\n",
        encoding="utf-8",
    )
    clean_pg_env.setenv("PG_ENABLED", "true")
    clean_pg_env.setenv("PG_HOST", "postgres")

    cfg = load_config(path=cfg_datei, load_env=False)

    assert cfg.postgres.enabled is True
    assert cfg.postgres.host == "postgres"


def test_pg_env_ohne_variablen_bleibt_yaml(tmp_path: Path, clean_pg_env):
    """Ohne PG_*-Variablen bleiben die config.yaml-Werte unverändert."""
    cfg_datei = tmp_path / "config.yaml"
    cfg_datei.write_text(
        "postgres:\n  enabled: false\n  host: localhost\n",
        encoding="utf-8",
    )

    cfg = load_config(path=cfg_datei, load_env=False)

    assert cfg.postgres.enabled is False
    assert cfg.postgres.host == "localhost"


def test_pg_enabled_falsy_wird_false(tmp_path: Path, clean_pg_env):
    """PG_ENABLED mit 'false' deaktiviert, auch wenn YAML true sagt."""
    cfg_datei = tmp_path / "config.yaml"
    cfg_datei.write_text("postgres:\n  enabled: true\n", encoding="utf-8")
    clean_pg_env.setenv("PG_ENABLED", "false")

    cfg = load_config(path=cfg_datei, load_env=False)

    assert cfg.postgres.enabled is False


def test_pg_port_ungueltig_wird_ignoriert(tmp_path: Path, clean_pg_env, capsys):
    """Ein nicht-numerisches PG_PORT wird ignoriert (Warnung, kein Crash)."""
    cfg_datei = tmp_path / "config.yaml"
    cfg_datei.write_text("postgres:\n  port: 5432\n", encoding="utf-8")
    clean_pg_env.setenv("PG_PORT", "keine-zahl")

    cfg = load_config(path=cfg_datei, load_env=False)

    assert cfg.postgres.port == 5432
    assert "PG_PORT" in capsys.readouterr().out
