import pytest

from sillon import core, updater


@pytest.mark.parametrize(
    ("title", "channel", "expected"),
    [
        ("Daft Punk - Get Lucky (Official Audio) ft. Pharrell Williams", "Daft Punk",
         ("Daft Punk", "Get Lucky ft. Pharrell Williams")),
        ("Stromae - Alors on danse (Clip Officiel)", "StromaeVEVO", ("Stromae", "Alors on danse")),
        ("Tata Yoyo", "Annie Cordy - Topic", ("Annie Cordy", "Tata Yoyo")),
        ("Indochine - Alice & June [Lyrics]", "random", ("Indochine", "Alice & June")),
        ("Song | Best of 2024", "Chan", ("Chan", "Song")),
    ],
)
def test_clean_metadata(title, channel, expected):
    assert core.clean_metadata(title, channel) == expected


def test_safe_filename():
    assert core.safe_filename('AC/DC: "Back" in *Black*?') == "ACDC Back in Black"
    assert core.safe_filename("...") == "morceau"


def test_guess_from_filename():
    assert core.guess_from_filename("Indochine - Alice & June.m4a") == ("Indochine", "Alice & June")
    assert core.guess_from_filename("piste.mp3") == ("", "piste")


def test_read_tags_rejects_garbage():
    with pytest.raises(ValueError):
        core.read_tags(b"not audio at all", "x.m4a")


@pytest.mark.parametrize(("a", "b"), [("v1.0.0", "1.0.1"), ("1.9.0", "1.10.0"), ("1.2.3", "v2.0.0")])
def test_version_order(a, b):
    assert updater.parse_version(a) < updater.parse_version(b)


def test_duration_text():
    r = core.SearchResult("x" * 11, "t", "c", 3725, "")
    assert r.duration_text == "1:02:05"
    assert core.SearchResult("x" * 11, "t", "c", 65, "").duration_text == "1:05"
