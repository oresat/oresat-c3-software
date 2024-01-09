"""OreSat C3 app main."""

import os
import socket
import time
from threading import Thread

from olaf import (
    Gpio,
    GpioError,
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
from .services.beacon import BeaconService
from .services.edl import EdlService
from .services.node_manager import NodeManagerService
from .services.radios import RadiosService
from .services.state import StateService


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


def get_hw_id(mock: bool) -> int:
    """
    Get the hardware ID of the C3 card.

    There are 5 gpio pins used to get the unique hardware of the card.
    """

    hw_id = 0
    try:
        for i in range(5):
            hw_id |= Gpio(f"HW_ID_BIT_{i}", mock).value << i
    except GpioError:
        pass
    logger.info(f"hardware id is 0x{hw_id:X}")
    return hw_id


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

        if not performance and (updating or edl):
            logger.info("setting cpufreq governor to performance mode")
            set_cpufreq_gov("performance")
            performance = True
        elif performance and not updating and not edl:
            logger.info("setting cpufreq governor to powersave mode")
            set_cpufreq_gov("powersave")
            performance = False


def main():
    """OreSat C3 app main."""

    path = os.path.dirname(os.path.abspath(__file__))

    args, config = olaf_setup("c3")
    mock_args = [i.lower() for i in args.mock_hw]
    mock_hw = len(mock_args) != 0

    # start watchdog thread ASAP
    thread = Thread(target=watchdog, daemon=True)
    thread.start()

    app.od["versions"]["sw_version"].value = __version__
    app.od["hw_id"].value = get_hw_id(mock_hw)

    state_service = StateService(config.fram_def, mock_hw)
    radios_service = RadiosService(mock_hw)
    beacon_service = BeaconService(config.beacon_def, radios_service)
    node_mgr_service = NodeManagerService(config.cards, mock_hw)
    edl_service = EdlService(app.node, radios_service, node_mgr_service, beacon_service)

    app.add_service(state_service)  # add state first to restore state from F-RAM
    app.add_service(radios_service)
    app.add_service(beacon_service)
    app.add_service(edl_service)
    app.add_service(node_mgr_service)

    for file_name in os.listdir(f"{path}/templates"):
        rest_api.add_template(f"{path}/templates/{file_name}")

    # on factory reset clear F-RAM
    app.set_factory_reset_callback(state_service.clear_state)

    olaf_run()


if __name__ == "__main__":
    main()
