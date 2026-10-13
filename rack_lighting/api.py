"""HTTP API for the front end.

    uvicorn rack_lighting.api:create_app --factory --host 0.0.0.0 --port 8000

The front end can only ask for a highlight. It cannot put a rack back to
idle: every highlight returns to the chase on its own after
`[Highlight] hold-seconds`.

    GET  /racks                       rack names and what each is showing
    PUT  /racks/{rack}/power
    POST /racks/{rack}/highlight      {"units": [1, 2]}
"""

import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from pydantic import AwareDatetime, BaseModel, Field

from . import config_loader
from .rack_lights import RackLights

log = logging.getLogger(__name__)


class HighlightRequest(BaseModel):
    units: list[int] = Field(min_length=1, examples=[[1, 2]])


class HighlightResponse(BaseModel):
    rack: str
    units: list[int]
    hold_seconds: float

class PowerReading(BaseModel):
    kw: float | None = Field(ge=0)
    measured_at: AwareDatetime

def create_app(cfg=None, lights=None):
    cfg = cfg or config_loader.load()
    lights = lights or RackLights(cfg)

    def check_token(authorization: str):
        if not cfg.power_ingest_token:
            raise HTTPException(401, "power ingest is not configured")
        expected = f"Bearer {cfg.power_ingest_token}"
        if not secrets.compare_digest(authorization.encode(), expected.encode()):
            raise HTTPException(401, "invalid token")

    @asynccontextmanager
    async def lifespan(app):
        # Start from a known state: every rack chasing.
        failed = lights.idle_all()
        if failed:
            log.warning("not reachable at startup: %s", ", ".join(failed))
        yield

    app = FastAPI(title="SCinet rack lighting", lifespan=lifespan)
    app.state.lights = lights

    @app.get("/racks")
    def racks():
        return {
            name: {"showing": list(lights.showing[name]) or "idle"}
            for name in cfg.racks
        }

    @app.put("/racks/{rack}/power", status_code=204)
    def set_power(rack: str, reading: PowerReading, authorization: str = Header()):
        # Get the given data from DevOPS side and pass it to animation side
        pass

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
