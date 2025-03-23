import socket
import sys
import time
from argparse import ArgumentParser

from loguru import logger
from oresat_libcanopend import NodeClient

from . import __version__
from .board.cpufreq import set_cpufreq_gov
from .board.gpio import Gpio, GpioError
from .gen.c3_od import C3Entry, C3Status, C3SystemReset, C3UpdaterStatus
from .gen.missions import Mission
from .services import Service
from .services.beacon import BeaconService
from .services.edl import EdlService
from .services.node_manager import NodeManagerService
from .services.radios import RadiosService
from .services.state import StateService
from .subsystems.rtc import set_system_time_to_rtc_time
from .ui import Ui


def get_hw_version() -> str:
    version = "0.0"
    try:
        with open("/sys/bus/i2c/devices/XXXX/eeprom", "rb") as f:
            raw = f.read(28)
            version = raw[12:16].decode()
            version = f"v{version[:2]}.{version[2:]}"
    except Exception:
        logger.error("failed to read hardware version from eeprom")
    return version


def get_hw_id(mock: bool) -> int:
    """
    Get the hardware ID of the C3 card.

    There are 5 gpio pins used to get the unique hardware of the v6.0 card.
    """

    hw_id = 0
    try:
        for i in range(5):
            hw_id |= Gpio(f"HW_ID_BIT_{i}", mock).value << i
    except GpioError:
        pass
    logger.info(f"hardware id is 0x{hw_id:X}")
    return hw_id


class Watchdog:
    def __init__(self, port: int = 20001):
        self._port = port
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def pet(self):
        self._socket.sendto(b"PET", ("localhost", self._port))

    def run(self, node: NodeClient, services: list[Service]):
        performance = True
        loop = 0

        while node.od_read(C3Entry.SYSTEM_RESET) == C3SystemReset.NO_STOP:
            time.sleep(1)
            loop += 1

            failed = 0
            flight_mode = node.od_read(C3Entry.FLIGHT_MODE)

            for service in services:  # pylint: disable=W0212
                failed += int(not service.is_running)
            if loop % 10 == 0 and (not flight_mode or failed == 0):
                logger.debug("watchdog pet")
                self.pet()

            if not flight_mode:
                continue

            updating = node.od_read(C3Entry.UPDATER_STATUS) == C3UpdaterStatus.IN_PROGRESS
            edl = node.od_read(C3Entry.STATUS) == C3Status.EDL

            if not performance and (updating or edl):
                logger.info("setting cpufreq governor to performance mode")
                set_cpufreq_gov("performance")
                performance = True
            elif performance and not updating and not edl:
                logger.info("setting cpufreq governor to powersave mode")
                set_cpufreq_gov("powersave")
                performance = False


def main():
    watchdog = Watchdog()
    watchdog.pet()  # pet watchdog ASAP

    oresat_nums = [str(m.nice_name[len("oresat") :]) for m in Mission]

    parser = ArgumentParser()
    parser.add_argument(
        "-o",
        "--oresat",
        choices=oresat_nums,
        default="0.5",
        help="oresat mission number",
    )
    parser.add_argument("-m", "--mock-hw", action="store_true", help="mock hardware")
    parser.add_argument("-v", "--verbose", action="store_true", help="verbose logging")
    args = parser.parse_args()

    if args.verbose:
        level = "DEBUG"
    else:
        level = "INFO"

    logger.remove()  # remove default logger
    logger.add(sys.stdout, level=level, backtrace=True)

    set_system_time_to_rtc_time()

    node = NodeClient(C3Entry)

    mission = Mission[f"ORESAT{args.oresat}".replace(".", "_")]
    node.od_write(C3Entry.SATELLITE_ID, mission.id)

    node.od_write(C3Entry.VERSIONS_SW_VERSION, __version__)
    node.od_write(C3Entry.VERSIONS_HW_VERSION, get_hw_version())
    if node.od_read(C3Entry.VERSIONS_HW_VERSION) == "6.0":
        node.od_write(C3Entry.HW_ID, get_hw_id(args.mock_hw))

    state_service = StateService(node, args.mock_hw)  # first to restore state from F-RAM
    radios_service = RadiosService(node, args.mock_hw)
    beacon_service = BeaconService(node, radios_service)
    node_mgr_service = NodeManagerService(node, args.mock_hw)
    edl_service = EdlService(node, radios_service, node_mgr_service, beacon_service)

    services = [
        state_service,
        radios_service,
        beacon_service,
        edl_service,
        node_mgr_service,
    ]

    for service in services:
        service.start()

    ui = Ui(node, node_mgr_service, beacon_service)
    ui.start()

    try:
        watchdog.run(node, services)
    except KeyboardInterrupt:
        pass

    for service in services:
        service.stop()  # put hw in a good state

    # on factory reset clear F-RAM
    reset = node.od_read(C3Entry.SYSTEM_RESET)
    if reset == C3SystemReset.FACTORY_RESET:
        state_service.clear_state()

    if reset != C3SystemReset.NO_STOP:
        logger.info(reset.name)


if __name__ == "__main__":
    main()
