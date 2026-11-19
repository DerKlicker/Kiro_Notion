"""Tests für die Property-Extraktion — die fehleranfälligste Stelle.

Die Beispiel-Seiten orientieren sich an echten Notion-Property-Strukturen
(Mitglieder, Gruppenstunden, Lager).
"""
from vereinsstatistik.properties import (
    extract_date_end,
    extract_value,
    map_page,
    page_title,
)


def test_title_and_rich_text():
    assert extract_value({"type": "title", "title": [{"plain_text": "Sommerlager"}]}) == "Sommerlager"
    assert extract_value({"type": "rich_text", "rich_text": [{"plain_text": "Wolf"}]}) == "Wolf"
    assert extract_value({"type": "rich_text", "rich_text": []}) == ""


def test_scalars():
    assert extract_value({"type": "number", "number": 12}) == 12
    assert extract_value({"type": "checkbox", "checkbox": True}) is True
    assert extract_value({"type": "select", "select": {"name": "Pfadfinder"}}) == "Pfadfinder"
    assert extract_value({"type": "select", "select": None}) is None
    assert extract_value({"type": "status", "status": {"name": "aktiv"}}) == "aktiv"


def test_date_start_and_end():
    prop = {"type": "date", "date": {"start": "2026-07-01", "end": "2026-07-10"}}
    assert extract_value(prop) == "2026-07-01"
    assert extract_date_end(prop) == "2026-07-10"
    assert extract_value({"type": "date", "date": None}) is None


def test_relation_returns_ids():
    prop = {"type": "relation", "relation": [{"id": "aaa"}, {"id": "bbb"}]}
    assert extract_value(prop) == ["aaa", "bbb"]


def test_multi_select():
    prop = {"type": "multi_select", "multi_select": [{"name": "Spiel"}, {"name": "Natur"}]}
    assert extract_value(prop) == ["Spiel", "Natur"]


def test_formula_and_rollup():
    assert extract_value({"type": "formula", "formula": {"type": "number", "number": 5}}) == 5
    rollup = {"type": "rollup", "rollup": {"type": "number", "number": 42}}
    assert extract_value(rollup) == 42
    rollup_arr = {
        "type": "rollup",
        "rollup": {"type": "array", "array": [
            {"type": "number", "number": 1},
            {"type": "number", "number": 2},
        ]},
    }
    assert extract_value(rollup_arr) == [1, 2]


def test_map_page_with_missing_optional_field():
    page = {
        "id": "page-1",
        "properties": {
            "Hauptthema": {"type": "title", "title": [{"plain_text": "Knoten"}]},
            "Datum": {"type": "date", "date": {"start": "2026-03-01"}},
            "Sippeneinteilung": {"type": "relation", "relation": [{"id": "m1"}, {"id": "m2"}]},
        },
    }
    field_map = {
        "titel": "Hauptthema",
        "datum": "Datum",
        "teilnehmer": "Sippeneinteilung",
        "zu_spaet": "Zu spät!",  # fehlt in der Seite -> None, kein Fehler
    }
    result = map_page(page, field_map)
    assert result["_id"] == "page-1"
    assert result["titel"] == "Knoten"
    assert result["datum"] == "2026-03-01"
    assert result["teilnehmer"] == ["m1", "m2"]
    assert result["zu_spaet"] is None


def test_page_title_finds_title_regardless_of_name():
    page = {"properties": {"Beliebig": {"type": "title", "title": [{"plain_text": "X"}]}}}
    assert page_title(page) == "X"
