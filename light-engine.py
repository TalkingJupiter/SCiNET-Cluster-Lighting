import asyncio
import time
from wled import WLED
from dataclasses import dataclass

RACK_START = 1  #Which pixel does the RACK starts
U_RANGE = 3     #How many pixels per U

PATTERN = [3,3,2]
U_COUNT = 42
STRIP_LEN = 301

#224 pixels per rack (112 per side)
#A controller will have 2 racks and per rack we have 1 primary 1 backup

@dataclass(frozen=True)
class Rack:
    host: str
    primary_start: int
    u_s: list


RACKS = {
    "A1": Rack("192.168.50.201", primary_start=1, backup_start=302),
    "A2": Rack("192.168.50.201", primary_start=302, backup_start=904),
    "B1": Rack("192.168.50.202", primary_start=1, backup_start=302),
    "B2": Rack("192.168.50.202", primary_start=603, backup_start=904),
    "C1": Rack("192.168.50.203", primary_start=1, backup_start=302),
    "C2": Rack("192.168.50.203", primary_start=603, backup_start=904),
    "D1": Rack("192.168.50.204", primary_start=1, backup_start=302),
    "D2": Rack("192.168.50.204", primary_start=603, backup_start=904),
}

CONTROLLER_LEN = 4 * STRIP_LEN

IDLE_STYLE = {
    "fx": 28,
    "sx": 160,
    "ix": 128,
    "pal": 0,
    "col": [[255, 120, 0], [0,0,0]],
    "bri": 255
}

HIGHLIGHT_STYLE = {
    "fx": 2,
    "sx": 160,
    "ix": 128,
    "pal": 0,
    "col": [[255, 255, 255], [0,0,0]],
    "bri": 150
}


IDLE_SEG = 0
PRIMARY_SEG = 1
BACKUP_SEG = 2

def u_range(u_start, u_count=1, rack_start=1):
    """Rack U position to LED indicies"""
    if u_start < 1 or u_start + u_count - 1 > U_COUNT:
        raise ValueError(f"U{u_start}+{u_count} outside 1..{U_COUNT}")

    n = len(PATTERN)
    lo = rack_start + sum(PATTERN[i%n] for i in range(u_start-1))
    hi = lo + sum(PATTERN[i%n] for i in range(u_start -1, u_start-1+ u_count))
    return lo, hi


class Controllers:
    """One WLED connection and one lock per controller host."""
    def __init__(self, racks):
        self.hosts = sorted({r.host for r in racks.values()})
        self.clients = {}
        self.locks = {}


    async def __aenter__(self):
        for host in self.hosts:
            self.clients[host] = WLED(host)
            self.locks[host] = asyncio.Lock()
        return self

    async def __aexit__(self, *exc):
        await asyncio.gather(
            *(c.close() for c in self.clients.values()),
            return_exceptions=True,
        )

    async def send(self, host, *segments):
        """Apply segment updates to once controller, serialized per host"""
        async with self.locks[host]:
            await self.clients[host].request("/json/state", method="POST", data={"seg": list(segments)})


async def idle(ctl, host):
    """IDLE animation across a controller's full strip"""

    await ctl.send(host, {
        "id": IDLE_SEG,
        "start": 0,
        "stop": CONTROLLER_LEN,
        "on": True,
        **IDLE_STYLE,
    })

async def highlight(ctl, rack_name, u_start, u_count=1):
    """Highlight a U range on both the primary and backup strip"""

    
    





async def triger(led, u, u_count=1):
    """Rack U Highlight Breathing Animation(White)"""
    lo, hi = u_range(u, u_count)
    await led.request("/json/state", method="POST", data={
                "seg": [
                    {"id":0, "on": False},
                    {
                    "id": 1,
                    "start": lo,
                    "stop": hi,
                    "fx": 2,
                    "sx": 160,
                    "ix": 128,
                    "pal": 0,
                    "col": [[255, 255, 255], [0,0,0]],
                    "on": True,
                    "bri": 150,
                }]
            })

async def idle(led, start, stop):
    """Idle Position: Chase Animation(Orangeish Color)"""
    await led.request("/json/state", method="POST", data={
            "seg": [{
                "id": 1,
                "start": 0,
                "stop": 301,
                "fx": 28,
                "sx": 160,
                "ix": 128,
                "pal": 0,
                "col": [[255, 120, 0], [0,0,0]],
                "on": True,
                "bri": 255,
            }]
        })


async def main() -> None:
    # lo, hi = u_range(11, 2)
    async with WLED("192.168.50.201") as led:
        device = await led.update()
        print(device.info.version)

        await led.master(on=True)

        while True:
            x = input()
            if x == "triger":
                await triger(led, 5, 1)
                await asyncio.sleep(10)

            if x == "exit":
                await led.master(on=False)
                break


if __name__ == "__main__":
    asyncio.run(main())