"""PUT and GET /racks/{rack}/power: DevOps pushes readings, anyone reads them."""

import dataclasses

import pytest
from fastapi.testclient import TestClient

from rack_lighting.api import create_app
from rack_lighting.power import PowerStore
from rack_lighting.rack_lights import RackLights
from tests.conftest import FakeClient, FakeClock, FakeTimers

TOKEN = "s3cret"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
READING = {"kw": 12.4, "measured_at": "2026-10-27T14:03:02Z"}
NOTHING = {"kw": None, "measured_at": None, "age_seconds": None}


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def power(cfg, clock):
    return PowerStore(cfg.racks, cfg.stale_after_seconds, clock=clock)


def make_api(cfg, power, token=TOKEN):
    cfg = dataclasses.replace(cfg, power_ingest_token=token)
    lights = RackLights(cfg, client_factory=FakeClient, schedule=FakeTimers())
    # raise_server_exceptions=False: a crash shows up as a 500 response, the
    # way a real client would see it, instead of failing the test with a
    # traceback. Several tests below exist to prove there is no 500.
    return TestClient(create_app(cfg, lights, power), raise_server_exceptions=False)


@pytest.fixture
def api(cfg, power):
    with make_api(cfg, power) as client:          # runs startup
        yield client


def put(api, rack="Rack1", body=READING, headers=AUTH):
    return api.put(f"/racks/{rack}/power", json=body, headers=headers)


def put_raw(api, text, rack="Rack1"):
    """Send a body that Python's json module can't produce from a dict, such
    as Infinity, the way another client might."""
    return api.put(
        f"/racks/{rack}/power",
        content=text,
        headers={**AUTH, "content-type": "application/json"},
    )


def reading(api, rack="Rack1"):
    """What GET reports for `rack`, without the rack name."""
    body = api.get(f"/racks/{rack}/power").json()
    body.pop("rack")
    return body


# ---------------------------------------------------------------- PUT: works

def test_put_stores_the_reading(api):
    r = put(api)
    assert r.status_code == 204
    assert r.content == b""
    assert reading(api) == {**READING, "age_seconds": 0.0}


def test_put_accepts_kw_null_as_no_data(api):
    assert put(api, body={"kw": None, "measured_at": READING["measured_at"]}).status_code == 204
    assert reading(api)["kw"] is None
    assert reading(api)["measured_at"] == READING["measured_at"]


def test_put_accepts_zero_kw(api):
    assert put(api, body={**READING, "kw": 0}).status_code == 204
    assert reading(api)["kw"] == 0


def test_older_reading_is_accepted_but_ignored(api):
    """A retried or delayed request must be harmless: 204, nothing changes."""
    put(api, body={"kw": 5.0, "measured_at": "2026-10-27T14:05:00Z"})
    assert put(api, body={"kw": 1.0, "measured_at": "2026-10-27T14:04:00Z"}).status_code == 204
    assert reading(api)["kw"] == 5.0


def test_resent_reading_is_accepted(api):
    put(api)
    assert put(api).status_code == 204


def test_timezones_are_compared_as_moments_not_text(api):
    """15:00+02:00 is 13:00 UTC, so it is older than 14:00Z even though the
    text "15" sorts after "14"."""
    put(api, body={"kw": 5.0, "measured_at": "2026-10-27T14:00:00Z"})
    put(api, body={"kw": 1.0, "measured_at": "2026-10-27T15:00:00+02:00"})
    assert reading(api)["kw"] == 5.0


def test_racks_are_independent(api):
    put(api, rack="Rack1", body={**READING, "kw": 1.0})
    put(api, rack="Rack2", body={**READING, "kw": 2.0})
    assert reading(api, "Rack1")["kw"] == 1.0
    assert reading(api, "Rack2")["kw"] == 2.0
    assert reading(api, "Rack3") == NOTHING


# ---------------------------------------------------------------- PUT: auth

@pytest.mark.parametrize("headers", [
    {},                                         # no header at all
    {"Authorization": ""},                      # empty
    {"Authorization": "Bearer nope"},           # wrong token
    {"Authorization": TOKEN},                   # right token, no "Bearer "
    {"Authorization": f"bearer {TOKEN}"},       # lowercase scheme
    {"Authorization": f"Bearer {TOKEN} "},      # trailing space
], ids=["missing", "empty", "wrong", "no-bearer", "lowercase", "trailing-space"])
def test_bad_credentials_are_401(api, headers):
    """Never 422: a missing header is a credentials problem, not bad data."""
    assert put(api, headers=headers).status_code == 401


def test_non_ascii_token_is_401_not_500(api):
    r = api.put(
        "/racks/Rack1/power",
        json=READING,
        headers=[(b"authorization", "Bearer é".encode())],
    )
    assert r.status_code == 401


def test_rejected_request_stores_nothing(api):
    put(api, headers={"Authorization": "Bearer nope"})
    assert reading(api) == NOTHING


@pytest.mark.parametrize("token", [None, ""])
def test_no_token_configured_rejects_everything(cfg, power, token):
    """Without a configured token the expected header would be "Bearer None"
    or "Bearer "; neither may get in."""
    with make_api(cfg, power, token=token) as api:
        for header in ("Bearer None", "Bearer ", f"Bearer {TOKEN}"):
            r = put(api, headers={"Authorization": header})
            assert r.status_code == 401
            assert r.json()["detail"] == "power ingest is not configured"


def test_unknown_rack_without_token_is_401_not_404(api):
    """The token is checked first, so rack names don't leak to strangers."""
    assert put(api, rack="Rack9", headers={}).status_code == 401


def test_unknown_rack_with_token_is_404(api):
    r = put(api, rack="Rack9")
    assert r.status_code == 404
    assert r.json()["detail"] == "unknown rack 'Rack9'"


# ---------------------------------------------------------------- PUT: bad data

@pytest.mark.parametrize("body", [
    {"kw": -5, "measured_at": READING["measured_at"]},
    {"kw": "a lot", "measured_at": READING["measured_at"]},
    {"measured_at": READING["measured_at"]},            # kw must be sent, even as null
    {"kw": 12.4},
    {"kw": 12.4, "measured_at": "2026-10-27T14:03:02"},  # no timezone
    {"kw": 12.4, "measured_at": "yesterday"},
    {},
], ids=["negative", "not-a-number", "no-kw", "no-time", "no-timezone", "not-a-time", "empty"])
def test_bad_data_is_422(api, body):
    assert put(api, body=body).status_code == 422
    assert reading(api) == NOTHING


@pytest.mark.parametrize("value", ["Infinity", "-Infinity", "NaN"])
def test_non_finite_kw_is_422_not_500(api, value):
    """FastAPI's default 422 echoes the bad value back, and JSON can't hold
    Infinity, so without our handler this would be a 500."""
    r = put_raw(api, f'{{"kw": {value}, "measured_at": "2026-10-27T14:03:02Z"}}')
    assert r.status_code == 422
    assert r.json()["detail"][0]["msg"] == "Input should be a finite number"
    assert reading(api) == NOTHING


def test_validation_errors_do_not_echo_the_sent_value(api):
    r = put(api, body={"kw": -5, "measured_at": "2026-10-27T14:03:02Z"})
    for error in r.json()["detail"]:
        assert "input" not in error


def test_handler_keeps_other_validation_errors_as_422(api):
    """The custom handler applies to every endpoint; highlights still work."""
    assert api.post("/racks/Rack1/highlight", json={"units": []}).status_code == 422


# ---------------------------------------------------------------- GET

def test_get_before_any_reading(api):
    r = api.get("/racks/Rack1/power")
    assert r.status_code == 200
    assert r.json() == {"rack": "Rack1", **NOTHING}


def test_get_reports_age_since_we_received_it(api, clock):
    put(api)
    clock.now = 3.5
    assert reading(api)["age_seconds"] == 3.5


def test_get_reports_nothing_once_stale(api, clock):
    put(api)
    clock.now = 30
    assert reading(api)["kw"] == 12.4, "exactly stale-after-seconds: still fresh"
    clock.now = 31
    assert reading(api) == NOTHING


def test_new_reading_after_stale_is_fresh_again(api, clock):
    put(api)
    clock.now = 40
    put(api, body={"kw": 9.8, "measured_at": "2026-10-27T14:03:42Z"})
    clock.now = 41
    assert reading(api) == {"kw": 9.8, "measured_at": "2026-10-27T14:03:42Z", "age_seconds": 1.0}


def test_get_needs_no_token(api):
    put(api)
    assert api.get("/racks/Rack1/power", headers={}).status_code == 200


def test_get_unknown_rack_is_404(api):
    r = api.get("/racks/Rack9/power")
    assert r.status_code == 404
    assert r.json()["detail"] == "unknown rack 'Rack9'"
