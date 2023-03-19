import os

from olaf import olaf_setup, olaf_run, app, rest_api, render_olaf_template

from .rtc import Rtc
from .opd import Opd
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

    rtc = Rtc(mock='rtc' in mock_args or 'all' in mock_args)
    opd = Opd(mock='opd' in mock_args or 'all' in mock_args)

    app.add_resource(StateResource(rtc))
    app.add_resource(BeaconResource())
    app.add_resource(EdlResource(opd, rtc))
    app.add_resource(OpdResource(opd))

    rest_api.add_template(f'{path}/templates/beacon.html')
    rest_api.add_template(f'{path}/templates/opd.html')

    olaf_run()


if __name__ == '__main__':
    main()
