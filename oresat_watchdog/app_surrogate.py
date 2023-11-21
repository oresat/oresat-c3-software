"""OreSat C3 app surrogate."""

import socket
from time import sleep

# constants
IP_ADDRESS = "127.0.0.1"
PORT = 20001


def main():
    """OreSat C3 app surrogate."""

    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    while True:
        udp_socket.sendto(b"PING", (IP_ADDRESS, PORT))
        sleep(10)


if __name__ == "__main__":
    main()
