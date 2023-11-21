# OreSat C3 Software

Main application for Octavo A8 with Debian Linux version of the C3 card.

The C3 card is the "flight" computer of OreSat. C3 stands for command,
control, and commuication. It handles all commuications and controls
the state of the satellite.

**Note:** For OreSat0, the C3 card used STM32F4 and ChibiOS, for that project
see the [oresat-firmware] repo and the `src/f4/app_control` directory.
The C3 card was converted to Octavo A8 card to simplify the code base
by swapping from heavily embedded system using ChibiOS to a general
Linux-environment using Python and make to use existing Python libraries.

Like all OreSat software projects it is built using OLAF (OreSat Linux App
Framework), which it built ontop of [CANopen for Python] project. See the
[oresat-olaf] repo for more info about OLAF.

## Quickstart

**For development**, install `oresat-configs` from the github repo at 
https://github.com/oresat/oresat-configs (not from PyPI). That repo may have
changes that are not apart of the latest release yet.

Install dependencies

```bash
$ pip3 install -r requirements.txt
```

Make a virtual CAN bus (skip if using a real CAN bus)

```bash
$ sudo ip link add dev vcan0 type vcan
$ sudo ip link set vcan0 up
```

Run the C3 app

```bash
$ python3 -m oresat_c3
```

Can select the CAN bus to use (`vcan0`, `can0`, etc) with the `-b BUS` arg.

Can mock hardware by using the `-m HARDWARE` flag.

- The`-m all` argument can be used to mock hardware (CAN bus is always
  required).
- The `-m opd` argument would only mock the hardware for the OPD subsystem and
  expect all other hardware
  to exist.
- The `-m fram` argument would only mock the F-RAM chip and expect all other
  hardware to exist.
- The `-m opd fram` argument would both mock the hardware for the OPD subsystem
  and the F-RAM chip and expect all other hardware to exist.

See other options with `-h` flag.

A basic [Flask]-based website for development and integration can be found at
`http://localhost:8000` when the software is running.

## Project Layout

- `docs/`: Source of Read the Docs documentation.
- `oresat_c3/`: Source code.
  - `data/`: Holds the CANopen EDS and DCF files for project.
  - `drivers/`: Fully stand-alone (doesn't import anything else from project)
    Pythonic drivers used by project. All drivers can mock hardware it's for.
  - `protocols/`: Anything dealing with packing or unpacking beacon and EDL
    packets.
  - `services/`: OLAF services, the "glue" between protocol, drivers, and/or
    subsystems with the CANopen node with a dedicated thread.
  - `subsystems/`: Anything dealing with the subsystems of the C3 other than the
    CAN bus.
  - `templates/`: The [Flask]-based templates to add OLAF's REST API to be used
    for development and integration (not used in production).
- `tests/`: Unit tests.

## Documentation

Project uses [Sphinx] to generate documentation.

Documentation is hosted on [Read the Docs], see https://oresat-c3-software.readthedocs.io/en/latest/

To manually build the documentation:

```bash
$ make -C docs html
```

Open `docs/build/html/index.html` in a web broswer

## Unit Tests

This project uses python's build in `unittest` module for unit testing.

To run units:

```bash
$ python3 -m unittest
```

By default all unit tests run with the hardware mocked. When running on the real
hardware set the `MOCK_HW` environment variable to `"false"` (case insensitive).

To run units when on real hardware:

```bash
$ MOCK_HW="false" python3 -m unittest
```

**Note:** The follow environment variables are also available:

- `I2C_BUS_NUM`: The I2C bus number used by the OPD and F-RAM.
- `FRAM_ADDR`: The I2C address for the F-RAM chip. Must be in hex (e.g., `"0x50"`)

[oresat-firmware]: https://github.com/oresat/oresat-firmware
[Flask]: https://flask.palletsprojects.com/en/latest/
[oresat-olaf]: https://github.com/oresat/oresat-olaf
[CANopen for Python]: https://github.com/christiansandberg/canopen
[Read the Docs]: https://readthedocs.org
[Sphinx]: https://www.sphinx-doc.org/en/master/
