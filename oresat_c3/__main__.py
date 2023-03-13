import os

from olaf import olaf_run, app

from .resources.beacon import BeaconResource
from .resources.edl import EdlResource
from .resources.state import StateResource


def main():

    app.add_resource(StateResource)  # state always first
    app.add_resource(BeaconResource)
    app.add_resource(EdlResource)

    olaf_run(f'{os.path.dirname(os.path.abspath(__file__))}/data/oresat_c3.dcf')


if __name__ == '__main__':
    main()
