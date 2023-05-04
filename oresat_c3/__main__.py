import os

from olaf import olaf_setup, olaf_run, app, rest_api, render_olaf_template

from .subsystems.opd import Opd
from .subsystems.fram import Fram
from .resources.beacon import BeaconResource
from .resources.edl import EdlResource
from .resources.opd import OpdResource
from .resources.state import StateResource


@rest_api.app.route('/beacon')
def edl_template():
    return render_olaf_template('beacon.html', name='Beacon')


@rest_api.app.route('/opd')
def opd_template():
    return render_olaf_template('opd.html', name='OPD (OreSat Power Domain)')


def main():

    path = os.path.dirname(os.path.abspath(__file__))

    args = olaf_setup(f'{path}/data/oresat_c3.dcf')
    mock_args = [i.lower() for i in args.mock_hw]
    mock_opd = 'opd' in mock_args or 'all' in mock_args
    mock_fram = 'fram' in mock_args or 'all' in mock_args

    # TODO get from OD
    i2c_bus_num = 2
    opd_enable_pin = 20
    fram_i2c_addr = 0x50

    opd = Opd(opd_enable_pin, i2c_bus_num, mock=mock_opd)
    fram = Fram(i2c_bus_num, fram_i2c_addr, mock=mock_fram)

    app.add_resource(StateResource(fram))  # add state first to restore state from F-RAM
    app.add_resource(BeaconResource())
    app.add_resource(EdlResource(opd))
    app.add_resource(OpdResource(opd))

    rest_api.add_template(f'{path}/templates/beacon.html')
    rest_api.add_template(f'{path}/templates/opd.html')

    # on factory reset clear F-RAM
    app.set_factory_reset_callback(fram.clear)

    olaf_run()


if __name__ == '__main__':
    main()
