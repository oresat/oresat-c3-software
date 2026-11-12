"""
Node manager service.
"""

import json
import os
import socket
from argparse import ArgumentParser


def tcp_request(func):
    def tcp_client_func(*args, **kwargs):
        HOST = "127.0.0.1"
        PORT = 9000
        cmd, nodes = func(*args, **kwargs)
        request = {"cmd": cmd, "nodes": nodes}

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            # check that connection works
            try:
                s.connect((HOST, PORT))
            except Exception:
                print("Server connection refused, please start server.")
                print(f"Expected host: {HOST}")
                print(f"Expected port: {PORT}")
                return

            s.sendall((json.dumps(request)).encode())
            # wait for confirm
            result = s.recv(1024)
            print(result)

    return tcp_client_func


def opd_start(args):
    print("Sorry you have to start the opd server yourself.")
    print("Please run the following:")
    print("python3 opd_server.py --help")


@tcp_request
def opd_print(args):
    return "print", args.nodes


@tcp_request
def opd_status(args):
    return "status", []


@tcp_request
def opd_probe(args):
    return "probe", args.nodes


@tcp_request
def opd_reset(args):
    return "reset", args.nodes


@tcp_request
def opd_scan(args):
    return "scan", []


@tcp_request
def opd_enable(args):
    return "enable", args.nodes


@tcp_request
def opd_disable(args):
    return "disable", args.nodes


@tcp_request
def opd_end(args):
    # don't send nodes
    return "end", []


if __name__ == "__main__":
    path = os.path.dirname(os.path.abspath(__file__))

    opd_parser = ArgumentParser("OPD_CLI", add_help=True)

    opd_subparsers = opd_parser.add_subparsers(required=True, help="Subparsers help menu \n")

    # print only lists info

    parser_start = opd_subparsers.add_parser(
        "start",
        description="[NOT IMPLEMENTED] start the OPD server (just background opd_server.py)",
        help="[NOT IMPLEMENTED] Start the OPD server (just background opd_server.py",
    )
    parser_start.set_defaults(func=opd_start)

    # print node info
    parser_print = opd_subparsers.add_parser(
        "print",
        description="[NOT IMPLEMENTED] Print information about one or more OPD nodes",
        help="[NOT IMPLEMENTED] print OPD nodes",
    )
    parser_print.add_argument(
        "nodes",
        nargs="+",
        help="Nodes of all cards to operate on (string or int).",
    )
    parser_print.set_defaults(func=opd_print)

    # print node status
    parser_status = opd_subparsers.add_parser(
        "status",
        description="Print information about one or more OPD statuses",
        help="Print OPD node statuses",
    )
    parser_status.add_argument(
        "nodes",
        nargs="*",
        help="Nodes of all cards to operate on (string or int).",
    )
    parser_status.set_defaults(func=opd_status)

    # scan
    parser_status = opd_subparsers.add_parser(
        "scan",
        description="Print number of detected OPD nodes.",
        help="Print number of detected OPD nodes.",
    )
    parser_status.set_defaults(func=opd_scan)

    # print node status
    parser_probe = opd_subparsers.add_parser(
        "probe", description="Probe (without reset)", help="Probe (without reset)"
    )
    parser_probe.add_argument(
        "nodes",
        nargs="*",
        help="Nodes of all cards to operate on (string or int).",
    )
    parser_probe.set_defaults(func=opd_probe)

    # print node status
    parser_reset = opd_subparsers.add_parser(
        "reset", description="Probe with reset", help="Probe with reset"
    )
    parser_reset.add_argument(
        "nodes",
        nargs="*",
        help="Nodes of all cards to operate on (string or int).",
    )
    parser_reset.set_defaults(func=opd_reset)

    parser_enable = opd_subparsers.add_parser(
        "enable", description="Enable one or more OPD nodes", help="Enable OPD nodes."
    )
    parser_enable.add_argument(
        "nodes",
        nargs="+",
        help="Nodes of all cards to operate on (string or int). May list more than 1",
    )
    parser_enable.set_defaults(func=opd_enable)

    parser_disable = opd_subparsers.add_parser(
        "disable", description="Disable one ore more OPD nodes", help="Disable OPD nodes"
    )
    parser_disable.add_argument(
        "nodes",
        nargs="+",
        help="Nodes of all cards to operate on (string or int). May list more than 1",
    )
    parser_disable.set_defaults(func=opd_disable)

    parser_print = opd_subparsers.add_parser(
        "end",
        description="End the OPD server at the other end of the TCP connection.",
        help="End the OPD server.",
    )
    parser_print.set_defaults(func=opd_end)

    args = opd_parser.parse_args()
    print(args)
    args.func(args)
