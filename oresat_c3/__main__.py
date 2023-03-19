import os

from olaf import olaf_setup, olaf_run, app

from .resources.beacon import BeaconResource
from .resources.edl import EdlResource
from .resources.state import StateResource
from .rtc import Rtc
from .opd import Opd


def main():

    args = olaf_setup(f'{os.path.dirname(os.path.abspath(__file__))}/data/oresat_c3.dcf')
    mock_args = [i.lower() for i in args.mock_hw]

    rtc = Rtc(mock='rtc' in mock_args or 'all' in mock_args)
    opd = Opd(mock='opd' in mock_args or 'all' in mock_args)

    app.add_resource(StateResource(rtc))
    app.add_resource(BeaconResource())
    app.add_resource(EdlResource(opd, rtc))

    olaf_run()


if __name__ == '__main__':
    main()
