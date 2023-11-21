"""OreSat C3 watchdog."""

import os
import signal
import socket
import sys
from argparse import ArgumentParser
from logging.handlers import SysLogHandler
from threading import Event, Thread
from time import time

from loguru import logger

# constants
IP_ADDRESS = "127.0.0.1"
PORT = 20001
BUFFER_SIZE = 1024
PING_TIMEOUT = 30
INHIBIT_TIMEOUT = 120
START_TS = time()

# globals
last_ts = time()
event = Event()


def gpio_find(name: str) -> int:
    """Find the GPIO number from a label name."""

    number = 0
    gpio_dir_path = "/sys/class/gpio"

    if not os.path.isdir(gpio_dir_path):
        raise ValueError("Could not find any gpios")

    for i in os.listdir(gpio_dir_path):
        if i.startswith("gpiochip") or i in ["export", "unexport"]:
            continue
        with open(f"{gpio_dir_path}/{i}/label", "r") as f:
            if f.read()[:-1] == name:
                number = int(i[4:])
                break

    if number == 0:
        raise ValueError(f"Could not find a gpio with label {name}")

    return number


def pet_thread():
    """Thread for petting the watchdog."""

    gpio_num = gpio_find("PET_WDT")
    gpio_path = f"/sys/class/gpio/gpio{gpio_num}/value"

    inhibit_time_reached = False
    while not event.is_set():
        if not inhibit_time_reached and time() > INHIBIT_TIMEOUT + START_TS:
            logger.info("inhibit time reached")
            inhibit_time_reached = True

        if inhibit_time_reached and time() > last_ts + PING_TIMEOUT:
            logger.error("no pings from app")
            break

        logger.debug("high")
        with open(gpio_path, "w") as f:
            f.write("1")
        event.wait(0.1)
        logger.debug("low")
        with open(gpio_path, "w") as f:
            f.write("0")
        event.wait(0.9)

    event.set()


def stop_thread(signo, _frame):
    """Stop the thread."""
    logger.debug(f"signal {signal.Signals(signo).name} was caught")
    event.set()


def main():
    """OreSat C3 watchdog main."""

    parser = ArgumentParser(prog="watchdog")
    parser.add_argument("-v", "--verbose", action="store_true", help="enable verbose logging")
    parser.add_argument("-l", "--log", action="store_true", help="log to only journald")
    args = parser.parse_args()

    if args.verbose:
        level = "DEBUG"
    else:
        level = "INFO"

    logger.remove()  # remove default logger
    if args.log:
        logger.add(SysLogHandler(address="/dev/log"), level=level)
    else:
        logger.add(sys.stdout, level=level)

    global last_ts  # pylint: disable=W0603
    udp_socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
    udp_socket.bind((IP_ADDRESS, PORT))
    udp_socket.settimeout(1)

    for sig in ["SIGTERM", "SIGHUP", "SIGINT"]:
        signal.signal(getattr(signal, sig), stop_thread)

    thread = Thread(target=pet_thread)
    thread.start()

    while not event.is_set():
        try:
            message, _ = udp_socket.recvfrom(BUFFER_SIZE)
        except TimeoutError:
            continue
        logger.debug(message)
        last_ts = time()

    event.set()
    thread.join()


if __name__ == "__main__":
    main()
