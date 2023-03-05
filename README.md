# oresat-c3-software

Software for Linux version of the C3 card.

## Quickstart

- Install dependenies `$ pip install -r requirements.txt`
- Make a virtual CAN bus
  - `$ sudo ip link add dev vcan0 type vcan`
  - `$ sudo ip link set vcan0 up`
- Run `$ python -m oresat_c3`
  - Can mock hardware by adding the `-m` flag
  - See other options with `-h` flag
