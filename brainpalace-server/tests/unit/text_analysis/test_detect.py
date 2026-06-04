from brainpalace_server.indexing.text_analysis.detect import detect_language


def test_detects_croatian_within_allowed_set():
    code = detect_language(
        "Naručivanje termina kod liječnika obiteljske medicine danas.",
        allowed={"hr", "en"},
        default="en",
        min_confidence=0.5,
    )
    assert code == "hr"


def test_detects_english():
    code = detect_language(
        "Please schedule a doctor appointment tomorrow morning.",
        allowed={"hr", "en"},
        default="hr",
        min_confidence=0.5,
    )
    assert code == "en"


def test_low_confidence_or_unknown_falls_back_to_default():
    assert (
        detect_language(
            "123 456", allowed={"hr", "en"}, default="hr", min_confidence=0.99
        )
        == "hr"
    )
