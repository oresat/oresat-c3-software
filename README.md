# OreSat C3 Software

Software for Linux version of the C3 card.

Like all OreSat software projects it is built using OLAF (OreSat Linux App
Framework). See the [oresat-olaf repo](https://github.com/oresat/oresat-olaf)
for more info about OLAF.

[Read the Docs](https://oresat-c3-software.readthedocs.io/en/latest/)

## Quickstart

- Install dependenies `$ pip3 install -r requirements.txt`
- Make a virtual CAN bus
  - `$ sudo ip link add dev vcan0 type vcan`
  - `$ sudo ip link set vcan0 up`
- Run `$ python3 -m oresat_c3`
  - Can select the CAN bus to use (`vcan0`, `can0`, etc) with the `-b BUS` arg.
  - Can mock hardware by using the `-m HARDWARE` flag.
    - The`-m all` can be used to mock all hardware (CAN bus is always required).
    - The `-m rtc` args would only mock the RTC and expect all other hardware to
      exist.
  - See other options with `-h` flag.
- A basic Flask-based website for development and integration can be found at
  `http://localhost:8000` when the software is running.

## Project Layout

- `docs`: Source of Read the Docs documentation.
- `oresat_c3`: Source code.
  - `data`: Holds the EDS and DCF files for project.
  - `drivers`: Fully stand-alone (doesn't import anything else from project)
    Pythonic drivers used by project. All drivers can mock hardware it's for.
  - `protocols`: Anything dealing with packing or unpacking beacon and EDL packets.
  - `resources`: OLAF resources, the "glue" between protocol, drivers, and/or
    subsystems with the CANopen node.
  - `subsystems`: Anything dealing with the subsystems of the C3 other than the
    CAN bus.
  - `templates`: The Flask-based templates to add OLAF's REST API to be used
    for development and integration (not used in production).
- `tests`: Unit tests.
