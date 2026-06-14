"""OreSat C3 app main."""

import logging
import os
import socket
import time
from threading import Thread

from olaf import (
    ServiceState,
    UpdaterState,
    app,
    logger,
    olaf_run,
    olaf_setup,
    render_olaf_template,
    rest_api,
    set_cpufreq_gov,
)

from . import C3State, __version__
from .protocols.cachestore import CacheStore
from .services.adcs_manager import ADCSManager
from .services.beacon import BeaconService
from .services.channel_router import ChannelRouterService
from .services.cop_manager import CopManagerService
from .services.edl import EdlService
from .services.node_flasher import NodeFlasherService
from .services.node_manager import NodeManagerService
from .services.radios import RadiosService
from .services.state import StateService
from .subsystems.rtc import set_system_time_to_rtc_time


class InterceptHandler(logging.Handler):
    def emit(self, record):
        # Map the logging level to loguru's level
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find the correct call depth so loguru reports the right source location
        frame, depth = logging.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1

        # + 2 to get into the new frame and out of the logging funciton in that frame
        logger.opt(depth=depth + 2, exception=record.exc_info).log(level, record.getMessage())


@rest_api.app.route("/beacon")
def beacon_template():
    """Render beacon template."""
    return render_olaf_template("beacon.html", name="Beacon")


@rest_api.app.route("/state")
def state_template():
    """Render state template."""
    return render_olaf_template("state.html", name="State")


@rest_api.app.route("/node-manager")
def node_mgr_template():
    """Render node manager template."""
    return render_olaf_template("node_manager.html", name="Node Manager")


@rest_api.app.route("/keys")
def keys_template():
    """Render keys template."""
    return render_olaf_template("keys.html", name="Keys")


def watchdog():
    """Pet the watchdog app (which pets the watchdog circuit)."""

    performance = True
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    loop = 0

    while True:
        time.sleep(1)
        loop += 1

        failed = 0
        flight_mode = app.od["flight_mode"].value

        for service in app._services:  # pylint: disable=W0212
            failed += int(service.status == ServiceState.FAILED)
        if loop % 10 == 0 and (not flight_mode or failed == 0):
            logger.debug("watchdog pet")
            udp_socket.sendto(b"PET", ("localhost", 20001))

        if not flight_mode:
            continue

        updating = app.od["updater"]["status"].value == UpdaterState.UPDATING
        edl = app.od["status"].value == C3State.EDL
        override = app.od["performance_override"].value

        if not performance and (updating or edl or override):
            logger.info("setting cpufreq governor to performance mode")
            set_cpufreq_gov("performance")
            performance = True
        elif performance and not (updating or edl or override):
            logger.info("setting cpufreq governor to powersave mode")
            set_cpufreq_gov("powersave")
            performance = False


def main():
    """OreSat C3 app main."""

    set_system_time_to_rtc_time()

    path = os.path.dirname(os.path.abspath(__file__))

    args, config = olaf_setup("c3")
    mock_args = [i.lower() for i in args.mock_hw]
    mock_hw = len(mock_args) != 0

    cop1_logger = logging.getLogger("ccsds_cop")
    cop1_logger.handlers = [InterceptHandler()]
    if args.verbose:
        cop1_logger.setLevel(logging.DEBUG)
    else:
        cop1_logger.setLevel(logging.INFO)
    cop1_logger.propagate = False

    # start watchdog thread ASAP
    thread = Thread(target=watchdog, daemon=True)
    thread.start()

    # The C3 needs a special OreSatFileCache that can speak CFDP
    app.node._fwrite_cache = CacheStore(app.node.fwrite_cache.dir)  # pylint: disable=W0212

    app.od["versions"]["sw_version"].value = __version__

    state_service = StateService(config.fram_def, mock_hw)
    radios_service = RadiosService(mock_hw)
    beacon_service = BeaconService(config.beacon_def, radios_service)
    node_mgr_service = NodeManagerService(config.cards, mock_hw=mock_hw)
    node_flasher_service = NodeFlasherService(app.node.fwrite_cache.dir, node_mgr_service)
    cop_service = CopManagerService()
    channel_router_service = ChannelRouterService(radios_service, cop_service)
    edl_service = EdlService(
        app.node, node_mgr_service, beacon_service, channel_router_service, node_flasher_service
    )
    adcs_mgr_service = ADCSManager()

    app.add_service(state_service)  # add state first to restore state from F-RAM
    app.add_service(radios_service)
    app.add_service(beacon_service)
    app.add_service(cop_service)
    app.add_service(channel_router_service)
    app.add_service(edl_service)
    app.add_service(node_mgr_service)
    app.add_service(adcs_mgr_service)

    for file_name in os.listdir(f"{path}/templates"):
        rest_api.add_template(f"{path}/templates/{file_name}")

    # on factory reset clear F-RAM
    app.set_factory_reset_callback(state_service.clear_state)

    olaf_run()


if __name__ == "__main__":
    main()
