import os
import configparser
from dotenv import load_dotenv

load_dotenv()
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")
config = configparser.ConfigParser()

if not config.read(CONFIG_PATH):
    raise FileNotFoundError(f"Unable to find config file: {CONFIG_PATH}")


redfish_username = os.environ.get('redfish_username')
redfish_password = os.environ.get('redfish_password')


racks = {}
for name in config.sections():
    if not name.startswith("Rack"):
        continue
    racks[name] = {
        "led_ip": config[name]["led-ip"],
        "redfish_ip" : [ip.strip() for ip in config[name]["redfish-ips"].split(',')]
    }

mode = config["Led-Controller"]["mode"]
pixel_count = config.getint("Led-Controller", "strip-pixel-count")
connection_type = config["Led-Controller"]["connection-type"]
min_kw = config.getfloat("Energy", "min-kw")
max_kw = config.getfloat("Energy", "max-kw")


#NOTE: Do we need to keep the low values or can we do it via prev high value?
low_energy_px_lo, low_energy_px_hi = [int(x) for x in config["Led-config"]["low-energy-pixel-range"].split(":")]
mid_energy_px_lo, mid_energy_px_hi = [int(x) for x in config["Led-config"]["mid-energy-pixel-range"].split(":")]
high_energy_px_lo, high_energy_px_hi = [int(x) for x in config["Led-config"]["high-energy-pixel-range"].split(":")]

if mode == "meter" and not( redfish_username or redfish_password):
    raise RuntimeError("The selected mode is meter but there is no username or password")
