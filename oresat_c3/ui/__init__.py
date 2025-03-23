import os
from threading import Thread
from typing import Union

from bottle import TEMPLATE_PATH, Bottle, request, template
from oresat_libcanopend import DataType, NodeClient

from ..__init__ import __version__
from ..gen.c3_od import C3Entry
from ..gen.missions import Mission
from ..services.beacon import BeaconService
from ..services.node_manager import NodeManagerService

TEMPLATE_PATH.append(os.path.dirname(os.path.abspath(__file__)))


class Ui:
    def __init__(self, node: NodeClient, node_manager: NodeManagerService, beacon: BeaconService):
        self.node = node
        self.beacon = beacon
        self.node_manager = node_manager

        sat_id = node.od_read(C3Entry.SATELLITE_ID)
        self.mission = Mission.from_id(sat_id)

        self.app = Bottle()
        self.thread = Thread(target=self._run, daemon=True)

        routes = [
            ("beacon", self.get_beacon_page, None, self.put_beacon_data),
            ("keys", self.get_keys_page, self.get_keys_data, self.put_keys_data),
            ("node-manager", self.get_nm_page, self.get_nm_data, self.put_nm_data),
            ("reset", self.get_reset_page, None, self.put_reset_data),
        ]

        self.app.route("/", "GET", self.get_index)
        self.app.route("/data/status", "GET", self.get_status_data)
        self.app.route("/data/status", "PUT", self.put_status_data)
        for name, get_page, get_data, put_data in routes:
            self.app.route(f"/{name}", "GET", get_page)
            if get_data:
                self.app.route(f"/data/{name}", "GET", get_data)
            self.app.route(f"/data/{name}", "PUT", put_data)

        # used by templates
        self.routes = [(route[0], route[0].replace("-", " ").title()) for route in routes]

    def _run(self):
        self.app.run(port=8000, quiet=True)

    def start(self):
        self.thread.start()

    def get_index(self):
        return template(
            "./index.tpl",
            mission=self.mission.nice_name,
            version=__version__,
            routes=self.routes,
            hw_version=self.node.od_read(C3Entry.VERSIONS_HW_VERSION),
            config_version=self.node.od_read(C3Entry.VERSIONS_CONFIGS_VERSION),
        )

    def get_entry(self, entry: Union[C3Entry, list[C3Entry]]):
        def bytes_to_str(value):
            if isinstance(value, bytes):
                value = value.hex()
            return value

        if isinstance(entry, C3Entry):
            entry = [entry]
        return {e.name: bytes_to_str(self.node.od_read(e)) for e in entry}

    def get_status_data(self):
        data = self.get_entry(C3Entry.FLIGHT_MODE)
        data["CANOPEND_STATUS"] = "CONNECTED" if self.node.is_connected else "DISCONNECTED"
        data["CAN_BUS_STATUS"] = self.node.bus_status.name
        return data

    def put_status_data(self):
        data = request.json
        entry = C3Entry.FLIGHT_MODE
        if entry.name in dict(data):
            self.node.od_write(entry, data[entry.name])

    def template(self, path: str):
        return template(
            path,
            mission=self.mission.nice_name,
            version=__version__,
            routes=self.routes,
        )

    def get_keys_page(self):
        return self.template("./keys.tpl")

    KEY_ENTRIES = [
        C3Entry.EDL_ACTIVE_CRYPTO_KEY,
        C3Entry.EDL_CRYPTO_KEY_0,
        C3Entry.EDL_CRYPTO_KEY_1,
        C3Entry.EDL_CRYPTO_KEY_2,
        C3Entry.EDL_CRYPTO_KEY_3,
    ]

    def get_keys_data(self) -> dict:
        return self.get_entry(self.KEY_ENTRIES)

    def put_keys_data(self):
        def parse_key_str(key: str) -> bytes:
            if len(key) != 64:
                raise ValueError(f"invalid key length of {len(key)}")
            return bytes.fromhex(key)

        data = request.json
        for e in self.KEY_ENTRIES:
            if e.name in data:
                if e.data_type == DataType.BYTES:
                    self.node.od_write(e, parse_key_str(data[e.name]))
                else:
                    self.node.od_write(e, data[e.name])

    def get_beacon_page(self):
        return self.template("./beacon.tpl")

    def put_beacon_data(self):
        self.beacon.send()

    def get_reset_page(self):
        return self.template("./reset.tpl")

    def put_reset_data(self):
        data = request.json
        entry = C3Entry.SYSTEM_RESET
        self.node.od_write(entry, entry.enum[data["reset"]])

    def get_nm_page(self):
        return self.template("./node_manager.tpl")

    def get_nm_data(self) -> dict:
        data = []
        for card in self.mission.nodes:
            data.append(
                {
                    "name": card.name,
                    "node_id": card.node_id,
                    "opd_addr": card.opd_address,
                    "status": self.node_manager.node_status(card.name).name,
                    "processor": card.processor.name,
                }
            )
        uart_node = self.node.od_read(C3Entry.OPD_UART_NODE_SELECT, use_enum=False)
        opd_status = self.node.od_read(C3Entry.OPD_STATUS).name
        return {
            "opd_status": opd_status,
            "opd_uart_node_select": uart_node,
            "nodes": data,
        }

    def put_nm_data(self):
        data = dict(request.json)
        if "opd_status" in data:
            value = C3Entry.OPD_STATUS.enum[data["opd_status"]]
            self.node.od_write(C3Entry.OPD_STATUS, value)
        if "opd_uart_node_select" in data:
            self.node.od_write(C3Entry.OPD_UART_NODE_SELECT, data["opd_uart_node_select"])

        if "node" in data and "state" in data:
            state = data["state"].upper()
            node = data["node"]
            if state == ["ENABLE", "BOOTLOADER"]:
                self.node_manager.enable(node, state == "BOOTLOADER")
            elif state == "DISABLE":
                self.node_manager.disable(node)
