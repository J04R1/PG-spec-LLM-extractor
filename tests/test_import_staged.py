"""Tests for scripts/import_staged_to_db.py — _normalize_cert()."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# scripts/ is not a package; add it to sys.path so we can import directly
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from import_staged_to_db import _normalize_cert


class TestNormalizeCertExisting:
    """Regression tests — cases that worked before this iteration."""

    def test_ccc(self):
        assert _normalize_cert("CCC") == ("CCC", "CCC")

    def test_civl_ccc(self):
        assert _normalize_cert("CIVL CCC") == ("CCC", "CCC")

    def test_en_b(self):
        assert _normalize_cert("EN B") == ("EN", "B")

    def test_en_slash_ltf_b(self):
        assert _normalize_cert("EN/LTF B") == ("EN", "B")

    def test_ltf_slash_en_b(self):
        assert _normalize_cert("LTF/EN B") == ("EN", "B")

    def test_dhv_prefix_1_2(self):
        assert _normalize_cert("DHV 1-2") == ("LTF", "1-2")

    def test_dhv_prefix_2(self):
        assert _normalize_cert("DHV 2") == ("LTF", "2")

    def test_bare_letter_b(self):
        assert _normalize_cert("B") == ("EN", "B")

    def test_bare_letter_a(self):
        assert _normalize_cert("A") == ("EN", "A")

    def test_load_test(self):
        assert _normalize_cert("Load test") == ("other", "Load test")

    def test_load_test_case_insensitive(self):
        assert _normalize_cert("load test") == ("other", "Load test")

    def test_none_returns_none(self):
        assert _normalize_cert(None) is None

    def test_empty_returns_none(self):
        assert _normalize_cert("") is None

    def test_dash_returns_none(self):
        assert _normalize_cert("-") is None


class TestNormalizeCertBareLTF:
    """New: bare numeric LTF classes (no DHV prefix)."""

    def test_bare_1(self):
        assert _normalize_cert("1") == ("LTF", "1")

    def test_bare_1_2(self):
        assert _normalize_cert("1-2") == ("LTF", "1-2")

    def test_bare_2(self):
        assert _normalize_cert("2") == ("LTF", "2")

    def test_bare_2_3(self):
        assert _normalize_cert("2-3") == ("LTF", "2-3")

    def test_bare_3(self):
        assert _normalize_cert("3") == ("LTF", "3")


class TestNormalizeCertDual:
    """New: transition-era dual LTF+EN certs — EN takes priority."""

    def test_1_slash_a_spaced(self):
        assert _normalize_cert("1 / A") == ("EN", "A")

    def test_1_slash_a_compact(self):
        assert _normalize_cert("1/A") == ("EN", "A")

    def test_1_slash_b_spaced(self):
        assert _normalize_cert("1 / B") == ("EN", "B")

    def test_1_slash_b_compact(self):
        assert _normalize_cert("1/B") == ("EN", "B")

    def test_1_2_slash_b_spaced(self):
        assert _normalize_cert("1-2 / B") == ("EN", "B")

    def test_1_2_slash_b_compact(self):
        assert _normalize_cert("1-2/B") == ("EN", "B")

    def test_2_slash_3(self):
        assert _normalize_cert("2/3") == ("EN", "C")

    def test_b_slash_1_2_spaced(self):
        assert _normalize_cert("B / 1-2") == ("EN", "B")

    def test_2_slash_b_spaced(self):
        assert _normalize_cert("2 / B") == ("EN", "B")
