import os
from threading import Thread
from typing import Union

from bottle import TEMPLATE_PATH, Bottle, request, template
from loguru import logger
from oresat_cand import DataType, ManagerNodeClient
from oresat_cand import __version__ as cand_version

from oresat_c3.subsystems.opd import OpdState

from ..__init__ import __version__
from ..gen.c3_od import C3Entry
from ..gen.cards import Card
from ..gen.missions import Mission
from ..services.beacon import BeaconService
from ..services.card_manager import CardManagerService

TEMPLATE_PATH.append(os.path.dirname(os.path.abspath(__file__)))


class Ui:
    def __init__(
        self, node: ManagerNodeClient, card_manager: CardManagerService, beacon: BeaconService
    ):
        self.node = node
        self.beacon = beacon
        self.card_manager = card_manager

        sat_id = node.od_read(C3Entry.SATELLITE_ID)
        self.mission = Mission.from_id(sat_id)

        self.app = Bottle()
        self.thread = Thread(target=self._run, daemon=True)

        routes = [
            ("beacon", self.get_beacon_page, None, self.put_beacon_data),
            ("card-manager", self.get_nm_page, self.get_nm_data, self.put_nm_data),
            ("keys", self.get_keys_page, self.get_keys_data, self.put_keys_data),
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
            cand_version=cand_version,
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
        data["CAND_STATUS"] = "CONNECTED" if self.node.is_connected else "DISCONNECTED"
        data["CAN_BUS_STATUS"] = self.node.bus_state.name
        return data

    def put_status_data(self):
        data = request.json
        entry = C3Entry.FLIGHT_MODE
        if entry.name in dict(data):
            action = "enabled " if data[entry.name] else "disabled"
            logger.warning(f"flight mode {action}")
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
                if e.data_type == DataType.OCTET_STR:
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
        return self.template("./card_manager.tpl")

    def get_nm_data(self) -> dict:
        data = []
        for card in self.mission.cards:
            data.append(
                {
                    "name": card.name,
                    "node_id": card.node_id,
                    "opd_addr": card.opd_address,
                    "status": self.card_manager.status(card).name,
                    "processor": card.processor.name,
                }
            )
        uart_card = self.card_manager.uart_card
        uart_card_addr = uart_card.opd_address if uart_card is not None else 0
        opd_status = self.card_manager.opd.status.name
        return {
            "opd_status": opd_status,
            "opd_uart_card_select": uart_card_addr,
            "cards": data,
        }

    def put_nm_data(self):
        data: dict = dict(request.json)
        if "opd_status" in data:
            state = OpdState[data["opd_status"]]
            if state == OpdState.ENABLED:
                self.card_manager.opd.enable()
            elif state == OpdState.DISABLED:
                self.card_manager.opd.disable()
        if "opd_uart_card_select" in data:
            uart_card_addr = data["opd_uart_card_select"]
            card = Card.from_opd_address(uart_card_addr) if uart_card_addr != 0 else None
            self.card_manager.uart_card = card

        if "card" in data and "state" in data:
            card = Card.from_name(data["card"])
            state = data["state"].upper()
            if state in ["ENABLE", "BOOTLOADER"]:
                self.card_manager.enable(card, state == "BOOTLOADER")
            elif state == "DISABLE":
                self.card_manager.disable(card)
