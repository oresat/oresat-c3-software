import os

from olaf import app, olaf_run, olaf_setup, render_olaf_template, rest_api
from oresat_od_db import BEACON_DEF_DB, OD_DB, NodeId, OreSatId

from . import __version__
from .services.beacon import BeaconService
from .services.edl import EdlService
from .services.opd import OpdService
from .services.state import StateService
from .subsystems.antennas import Antennas
from .subsystems.fram import Fram
from .subsystems.opd import Opd


@rest_api.app.route("/beacon")
def edl_template():
    return render_olaf_template("beacon.html", name="Beacon")


@rest_api.app.route("/opd")
def opd_template():
    return render_olaf_template("opd.html", name="OPD (OreSat Power Domain)")


@rest_api.app.route("/state")
def state_template():
    return render_olaf_template("state.html", name="State")


def main():
    path = os.path.dirname(os.path.abspath(__file__))

    args = olaf_setup(OD_DB, NodeId.C3)
    mock_args = [i.lower() for i in args.mock_hw]
    mock_opd = "opd" in mock_args or "all" in mock_args
    mock_fram = "fram" in mock_args or "all" in mock_args
    mock_ant = "antennas" in mock_args or "all" in mock_args

    app.od["versions"]["sw_version"].value = __version__
    oresat_id = app.od["satellite_id"].value

    beacon_def = BEACON_DEF_DB[OreSatId(oresat_id)]
    i2c_bus_num = 2
    opd_not_enable_pin = "OPD_nENABLE"
    opd_not_fault_pin = "OPD_nFAULT"
    opd_adc_current_pin = 2
    fram_i2c_addr = 0x50

    antennas = Antennas(mock_ant)
    opd = Opd(
        opd_not_enable_pin, opd_not_fault_pin, opd_adc_current_pin, i2c_bus_num, mock=mock_opd
    )
    fram = Fram(i2c_bus_num, fram_i2c_addr, mock=mock_fram)

    app.add_service(StateService(fram, antennas))  # add state first to restore state from F-RAM
    app.add_service(BeaconService(beacon_def))
    app.add_service(EdlService(opd))
    app.add_service(OpdService(opd))

    rest_api.add_template(f"{path}/templates/beacon.html")
    rest_api.add_template(f"{path}/templates/opd.html")
    rest_api.add_template(f"{path}/templates/state.html")

    # on factory reset clear F-RAM
    app.set_factory_reset_callback(fram.clear)

    olaf_run()


if __name__ == "__main__":
    main()
