"""Tests for brainpalace_server.indexing.text_analysis.base."""

import unicodedata

from brainpalace_server.indexing.text_analysis.base import TOKEN_RE, normalize


def test_normalize_lowercases_and_preserves_croatian_diacritics():
    assert normalize("LiječnIK ČĆŠŽĐ") == "liječnik čćšžđ"


def test_normalize_nfc_folds_combining_forms():
    # Construct the decomposed form explicitly so this is a genuine NFC test,
    # not a no-op. NFD("č") == c (U+0063) + COMBINING CARON (U+030C).
    decomposed = unicodedata.normalize("NFD", "č")  # 2 codepoints
    assert len(decomposed) == 2, "precondition: must be decomposed"
    # normalize() must collapse it back to the single NFC codepoint U+010D.
    result = normalize(decomposed)
    assert result == "č"  # U+010D, single codepoint
    assert len(result) == 1


def test_token_re_keeps_diacritics_and_splits_on_nonword():
    assert TOKEN_RE.findall("termin, kod doktora!") == ["termin", "kod", "doktora"]
    tokens = TOKEN_RE.findall("liječnik")
    assert len(tokens) == 1
    assert "č" in tokens[0]
