"""Tests fürs Laden/Speichern der Konfiguration und das DB-Mapping."""
from pathlib import Path

from vereinsstatistik.config import Config, load_config, save_config


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
