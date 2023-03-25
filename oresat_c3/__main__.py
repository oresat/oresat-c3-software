import os

from olaf import olaf_setup, olaf_run, app, rest_api, render_olaf_template

from .subsystems.rtc import Rtc
from .subsystems.opd import Opd
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
    mock_rtc = 'rtc' in mock_args or 'all' in mock_args
    mock_opd = 'opd' in mock_args or 'all' in mock_args

    rtc = Rtc(mock=mock_rtc)
    opd = Opd(20, mock=mock_opd)

    app.add_resource(StateResource(rtc))  # add state first
    app.add_resource(BeaconResource())
    app.add_resource(EdlResource(opd, rtc))
    app.add_resource(OpdResource(opd))

    rest_api.add_template(f'{path}/templates/beacon.html')
    rest_api.add_template(f'{path}/templates/opd.html')

    olaf_run()


if __name__ == '__main__':
    main()
