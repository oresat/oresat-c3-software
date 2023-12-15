"""OreSat C3 app main."""

import os
import socket
from threading import Event, Thread

from olaf import (
    Gpio,
    GpioError,
    ServiceState,
    app,
    logger,
    olaf_run,
    olaf_setup,
    render_olaf_template,
    rest_api,
)

from . import __version__
from .services.beacon import BeaconService
from .services.edl import EdlService
from .services.node_manager import NodeManagerService
from .services.radios import RadiosService
from .services.state import StateService
from .services.adcs import AdcsService


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


def watchdog(event: Event):
    """Pet the watchdog app (which pets the watchdog circuit)."""

    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    while not event.is_set():
        failed = 0
        for service in app._services:  # pylint: disable=W0212
            failed += int(service.status == ServiceState.FAILED)
        if not app.od["flight_mode"].value or failed == 0:
            logger.debug("watchdog pet")
            udp_socket.sendto(b"PET", ("localhost", 20001))
            event.wait(10)


def main():
    """OreSat C3 app main."""

    path = os.path.dirname(os.path.abspath(__file__))

    args, config = olaf_setup("c3")
    mock_args = [i.lower() for i in args.mock_hw]
    mock_hw = len(mock_args) != 0

    # start watchdog thread ASAP
    event = Event()
    thread = Thread(target=watchdog, args=(event,))
    thread.start()

    app.od["versions"]["sw_version"].value = __version__
    app.od["hw_id"].value = get_hw_id(mock_hw)

    state_service = StateService(config.fram_def, mock_hw)
    radios_service = RadiosService(mock_hw)
    beacon_service = BeaconService(config.beacon_def, radios_service)
    node_mgr_service = NodeManagerService(config.cards, mock_hw)
    edl_service = EdlService(radios_service, node_mgr_service, beacon_service)
    adcs_service = AdcsService(config)

    app.add_service(state_service)  # add state first to restore state from F-RAM
    app.add_service(radios_service)
    app.add_service(beacon_service)
    app.add_service(edl_service)
    app.add_service(adcs_service)
    app.add_service(node_mgr_service)

    rest_api.add_template(f"{path}/templates/beacon.html")
    rest_api.add_template(f"{path}/templates/state.html")
    rest_api.add_template(f"{path}/templates/node_manager.html")

    # on factory reset clear F-RAM
    app.set_factory_reset_callback(state_service.clear_state)

    olaf_run()

    # stop watchdog thread
    event.set()
    thread.join()


if __name__ == "__main__":
    main()
