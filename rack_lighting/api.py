"""HTTP API for the front end.

    uvicorn rack_lighting.api:create_app --factory --host 0.0.0.0 --port 8000

The front end can only ask for a highlight. It cannot put a rack back to
idle: every highlight returns to idle (the chase, or the kW meter in meter
mode) on its own after `[Highlight] hold-seconds`.

    GET  /health                      the process is up (no controller calls)
    GET  /status                      controllers reachable? 503 if none are
    GET  /racks                       rack names and what each is showing
    PUT  /racks/{rack}/power          DevOps pushes a reading (bearer token)
    GET  /racks/{rack}/power          the latest reading, if fresh
    POST /racks/{rack}/highlight      {"units": [1, 2]}
"""

import logging
import secrets
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, Field

from . import config_loader
from .power import PowerStore
from .rack_lights import RackLights
from .status import ControllerChecker, overall

log = logging.getLogger(__name__)


class HighlightRequest(BaseModel):
    units: list[int] = Field(min_length=1, examples=[[1, 2]])


class HighlightResponse(BaseModel):
    rack: str
    units: list[int]
    hold_seconds: float


class PowerResponse(BaseModel):
    rack: str
    kw: float | None
    measured_at: AwareDatetime | None
    age_seconds: float | None


class PowerReading(BaseModel):
    kw: float | None = Field(ge=0, allow_inf_nan=False)
    measured_at: AwareDatetime


class ControllerStatus(BaseModel):
    reachable: bool
    racks: list[str]
    wled_version: str | None
    led_count: int | None
    expected_led_count: int
    led_count_mismatch: bool | None
    uptime_s: int | None
    reboots: int
    last_error: str | None
    checked_at: AwareDatetime


class RackStatus(BaseModel):
    showing: list[int] | Literal["idle"]
    hold_remaining_s: float | None
    kw: float | None
    kw_age_s: float | None


class StatusResponse(BaseModel):
    status: Literal["ok", "degraded", "down"]
    mode: str
    controllers: dict[str, ControllerStatus]
    racks: dict[str, RackStatus]


def create_app(cfg=None, lights=None, power=None, checker=None):
    cfg = cfg or config_loader.load()
    power = power or PowerStore(cfg.racks, cfg.stale_after_seconds)
    # The meter must read the same store the PUT endpoint writes to.
    lights = lights or RackLights(cfg, power=power)
    checker = checker or ControllerChecker(cfg, lights)

    def check_token(authorization: str | None):
        if not cfg.power_ingest_token:
            raise HTTPException(401, "power ingest is not configured")
        if not authorization:
            raise HTTPException(401, "missing authorization header")
        expected = f"Bearer {cfg.power_ingest_token}"
        if not secrets.compare_digest(authorization.encode(), expected.encode()):
            raise HTTPException(401, "invalid token")

    @asynccontextmanager
    async def lifespan(app):
        # Start from a known state: every rack idle (chase or meter).
        failed = lights.idle_all()
        if failed:
            log.warning("not reachable at startup: %s", ", ".join(failed))
        # Keeps meters current and resends state to controllers that
        # rebooted; it also retries the ones that were down just now.
        stop_meter = lights.start_meter()
        try:
            yield
        finally:
            stop_meter()

    app = FastAPI(title="SCinet rack lighting", lifespan=lifespan)
    app.state.lights = lights

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # FastAPI's default reply echoes the rejected value back. If that value is
        # Infinity or NaN, turning the reply into JSON fails, and the caller gets a
        # 500 instead of a 422. Leave the value out.
        errors = [{k: v for k, v in e.items() if k != "input"} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.get("/health")
    def health():
        # Liveness only: if this answers, the process is up. It touches no
        # controller, so a dead controller can't make it fail or hang.
        return {"status": "ok"}

    # Plain `def`: probing blocks (on the network and the controller locks).
    @app.get("/status", response_model=StatusResponse,
             responses={503: {"description": "No controller is reachable"}})
    def status(response: Response):
        controllers = checker.controllers()
        state = overall(controllers)
        if state == "down":
            response.status_code = 503
        return StatusResponse(
            status=state,
            mode=cfg.mode,
            controllers=controllers,
            racks={name: rack_status(name) for name in cfg.racks},
        )

    def rack_status(name):
        remaining = lights.hold_remaining(name)
        reading = power.get(name)
        return RackStatus(
            showing=list(lights.showing[name]) or "idle",
            hold_remaining_s=None if remaining is None else round(remaining, 1),
            kw=None if reading is None else reading.kw,
            kw_age_s=None if reading is None else round(power.age(reading), 1),
        )

    @app.get("/racks")
    def racks():
        return {
            name: {"showing": list(lights.showing[name]) or "idle"}
            for name in cfg.racks
        }

    @app.put("/racks/{rack}/power", status_code=204)
    def set_power(rack: str, reading: PowerReading, authorization: str | None = Header(default=None)):
        # Store only; the meter reads from the store.
        check_token(authorization)
        if rack not in cfg.racks:
            raise HTTPException(404, f"unknown rack {rack!r}")
        power.update(rack, reading.kw, reading.measured_at)

    @app.get("/racks/{rack}/power", response_model=PowerResponse)
    def get_power(rack: str):
        if rack not in cfg.racks:
            raise HTTPException(404, f"unknown rack {rack!r}")
        reading = power.get(rack)
        if reading is None:
            return PowerResponse(rack=rack, kw=None, measured_at=None, age_seconds=None)
        return PowerResponse(rack=rack, kw=reading.kw, measured_at=reading.measured_at, age_seconds=power.age(reading))

    # Plain `def`, not `async def`: the WLED client blocks, so FastAPI runs
    # this in its thread pool instead of stalling every other request.
    @app.post("/racks/{rack}/highlight", response_model=HighlightResponse)
    def highlight(rack: str, body: HighlightRequest):
        try:
            units = lights.highlight(rack, body.units)
        except KeyError as exc:
            raise HTTPException(404, str(exc.args[0]))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        except OSError as exc:
            raise HTTPException(502, f"{rack} controller unreachable: {exc}")
        return HighlightResponse(
            rack=rack, units=list(units), hold_seconds=cfg.highlight_hold_s
        )

    return app
