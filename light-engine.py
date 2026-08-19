import asyncio
import time
from wled import WLED

RACK_START = 1  #Which pixel does the RACK starts
U_RANGE = 3     #How many pixels per U
PATTERN = [3,3,2]

#224 pixels per rack (112 per side)
#A controller will have 2 racks and per rack we have 1 primary 1 backup

def u_range(u_start, u_count=1):
    """Rack U position to LED indicies"""
    lo = RACK_START + sum(PATTERN[i%3] for i in range(u_start-1))
    hi = lo + sum(PATTERN[i%3] for i in range(u_start -1, u_start-1+ u_count))
    return lo, hi

async def trigger(led, u, u_count=1):
    """Rack U Highlight Breathing Animation(White)"""
    lo, hi = u_range(u, u_count)
    await led.request("/json/state", method="POST", data={
                "seg": [{
                    "id": 1,
                    "start": lo,
                    "stop": hi,
                    "fx": 2,
                    "sx": 160,
                    "ix": 128,
                    "pal": 0,
                    "col": [[255, 255, 255], [0,0,0]],
                    "on": True,
                    "bri": 255,
                }]
            })

async def off(led, start, stop):
    await led.request("/json/state", method="POST", data={
        "seg": [{
            "id": 1,
            "start": start,
            "stop": stop,
            "fx": 2,
            "sx": 160,
            "ix": 128,
            "pal": 0,
            "col": [[0,0,0], [0,0,0]],
            "on": True,
            "bri": 0,
            }]
        })

async def idle(led, start, stop):
    """Idle Position: Chase Animation(Orangeish Color)"""
    await led.request("/json/state", method="POST", data={
            "seg": [{
                "id": 1,
                "start": start,
                "stop": stop,
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
    async with WLED("192.168.1.134") as led:
        device = await led.update()
        print(device.info.version)

        # turn off all the LEDs first
        await led.off(led,0, 301)
        await led.master(on=True)
        for i in range(1, 43):
            await trigger(led, i, 1)
            await asyncio.sleep(3)

        await idle(led, 0, 301)


if __name__ == "__main__":
    asyncio.run(main())
