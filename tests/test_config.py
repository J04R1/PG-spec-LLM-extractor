"""Tests for configuration loading and output path management."""

from pathlib import Path

from src.config import get_output_paths, load_config


class TestLoadConfig:
    def test_load_ozone_config(self):
        cfg = load_config("config/manufacturers/ozone.yaml")
        assert cfg["manufacturer"]["slug"] == "ozone"
        assert "sources" in cfg or "extraction" in cfg

    def test_config_has_manufacturer_name(self):
        cfg = load_config("config/manufacturers/ozone.yaml")
        assert cfg["manufacturer"]["name"]


class TestGetOutputPaths:
    def test_returns_expected_keys(self):
        paths = get_output_paths("ozone")
        expected_keys = {"raw_json", "partial", "csv", "urls", "db"}
        assert set(paths.keys()) == expected_keys

    def test_paths_contain_slug(self):
        paths = get_output_paths("ozone")
        assert "ozone" in str(paths["raw_json"])
        assert "ozone" in str(paths["csv"])

    def test_db_path_shared(self):
        paths = get_output_paths("ozone")
        assert paths["db"].name == "paragliders.db"

    def test_paths_are_path_objects(self):
        paths = get_output_paths("test_mfr")
        for key, val in paths.items():
            assert isinstance(val, Path), f"{key} should be a Path"
