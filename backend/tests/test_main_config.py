from app.main import _parse_cors_origins


def test_parse_cors_origins_single():
    assert _parse_cors_origins("http://localhost:5173") == ["http://localhost:5173"]


def test_parse_cors_origins_multiple_comma_separated():
    assert _parse_cors_origins("https://a.example.com, https://b.example.com") == [
        "https://a.example.com",
        "https://b.example.com",
    ]


def test_parse_cors_origins_ignores_empty_segments():
    assert _parse_cors_origins("https://a.example.com,,") == ["https://a.example.com"]
