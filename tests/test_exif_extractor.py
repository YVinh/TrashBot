import pytest

from exif_extractor import convert_to_degrees


def test_convert_to_degrees_basic():
    # 50 deg, 30 min, 0 sec -> 50.5 decimal degrees
    assert convert_to_degrees((50, 30, 0)) == pytest.approx(50.5)


def test_convert_to_degrees_zero():
    assert convert_to_degrees((0, 0, 0)) == 0.0


def test_convert_to_degrees_invalid_length_returns_none():
    assert convert_to_degrees((1, 2)) is None


def test_convert_to_degrees_non_numeric_returns_none():
    assert convert_to_degrees(("a", "b", "c")) is None


def test_convert_to_degrees_non_sequence_returns_none():
    assert convert_to_degrees(None) is None
