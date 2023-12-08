"""OreSat C3 app main."""

import os

from olaf import Gpio, GpioError, app, logger, olaf_run, olaf_setup, render_olaf_template, rest_api
from oresat_configs import NodeId

from . import __version__
from .drivers.fm24cl64b import Fm24cl64b
from .services.beacon import BeaconService
from .services.edl import EdlService
from .services.opd import OpdService
from .services.state import StateService
from .services.adcs import AdcsService
from .subsystems.antennas import Antennas
from .subsystems.opd import Opd


@rest_api.app.route("/beacon")
def beacon_template():
    """Render beacon template."""
    return render_olaf_template("beacon.html", name="Beacon")


@rest_api.app.route("/opd")
def opd_template():
    """Render OPD template."""
    return render_olaf_template("opd.html", name="OPD (OreSat Power Domain)")


@rest_api.app.route("/state")
def state_template():
    """Render state template."""
    return render_olaf_template("state.html", name="State")


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


def main():
    """OreSat C3 app main."""
    path = os.path.dirname(os.path.abspath(__file__))

    args, config = olaf_setup(NodeId.C3)
    mock_args = [i.lower() for i in args.mock_hw]
    mock_opd = "opd" in mock_args or "all" in mock_args
    mock_fram = "fram" in mock_args or "all" in mock_args
    mock_ant = "antennas" in mock_args or "all" in mock_args

    app.od["versions"]["sw_version"].value = __version__
    app.od["hw_id"].value = get_hw_id("all" in mock_args)

    beacon_def = config.beacon_def
    fram_def = config.fram_def

    i2c_bus_num = 2
    opd_not_enable_pin = "OPD_nENABLE"
    opd_not_fault_pin = "OPD_nFAULT"
    opd_adc_current_pin = 2
    fram_i2c_addr = 0x50

    antennas = Antennas(mock_ant)
    opd = Opd(
        opd_not_enable_pin, opd_not_fault_pin, opd_adc_current_pin, i2c_bus_num, mock=mock_opd
    )
    fram = Fm24cl64b(i2c_bus_num, fram_i2c_addr, mock=mock_fram)

    app.add_service(
        StateService(fram, fram_def, antennas)
    )  # add state first to restore state from F-RAM
    app.add_service(BeaconService(beacon_def))
    app.add_service(EdlService(opd))
    app.add_service(OpdService(opd))
    app.add_service(AdcsService(opd))

    rest_api.add_template(f"{path}/templates/beacon.html")
    rest_api.add_template(f"{path}/templates/opd.html")
    rest_api.add_template(f"{path}/templates/state.html")

    # on factory reset clear F-RAM
    app.set_factory_reset_callback(fram.clear)

    olaf_run()


if __name__ == "__main__":
    main()
