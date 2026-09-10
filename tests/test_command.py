from backend.services.command import interpret, match_nodes

NODES = [
    {"id": 101, "name": "Delhi"},
    {"id": 124, "name": "Mumbai"},
    {"id": 110, "name": "Kolkata"},
    {"id": 1, "name": "Gandhipuram"},
    {"id": 6, "name": "Singanallur"},
    {"id": 4, "name": "Peelamedu"},
    {"id": 35 - 15, "name": "Sathy Rd (Saravanampatti - Peelamedu)"},
]


def test_route_full_form():
    a = interpret("Route Delhi to Mumbai", NODES)
    assert a["action"] == "route"
    assert (a["src"]["id"], a["dst"]["id"]) == (101, 124)


def test_route_bare_form():
    a = interpret("Gandhipuram to Singanallur", NODES)
    assert a["action"] == "route"


def test_route_arrow_form():
    a = interpret("route Delhi -> Mumbai", NODES)
    assert a["action"] == "route"


def test_fuzzy_prefix_match():
    assert match_nodes("delh", NODES)[0]["name"] == "Delhi"
    assert match_nodes("MUM", NODES)[0]["name"] == "Mumbai"


def test_ambiguous_route_clarifies():
    a = interpret("Route Delhi to nowhere-xyz", NODES)
    assert a["action"] == "clarify_route"
    assert a["src_options"] and a["dst_options"] == []


def test_traffic_request():
    a = interpret("Traffic on Sathy Rd", NODES)
    assert a["action"] == "traffic_request"


def test_jam_request_with_count():
    a = interpret("Jam Peelamedu 40", NODES)
    assert a["action"] == "jam_request" and a["count"] == 40


def test_jam_request_default_count():
    a = interpret("jam Peelamedu", NODES)
    assert a["count"] == 30


def test_congested_synonyms():
    for text in ("congested", "Where is it jammed?", "traffic", "stats", "reset"):
        assert interpret(text, NODES)["action"] in (
            "congested", "stats", "reset"), text


def test_unknown():
    a = interpret("blabla nonsense", NODES)
    assert a["action"] == "unknown"


def test_help_empty():
    assert interpret("", NODES)["action"] == "help"
    assert interpret("help", NODES)["action"] == "help"
