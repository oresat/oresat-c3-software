from dataclasses import astuple
from time import time

from loguru import logger
from oresat_cand import ManagerNodeClient

from ..gen.c3_od import C3Entry, C3SystemReset
from ..gen.cards import Card
from ..gen.edl_commands import (
    CoNodeEnableEdlRequest,
    CoNodeEnableEdlResponse,
    CoNodeStatusEdlRequest,
    CoNodeStatusEdlResponse,
    CoSdoReadEdlRequest,
    CoSdoReadEdlResponse,
    CoSdoWriteEdlRequest,
    CoSdoWriteEdlResponse,
    EdlCommandId,
    EdlCommandRequest,
    EdlCommandResponse,
    OpdEnableEdlRequest,
    OpdEnableEdlResponse,
    OpdProbeEdlRequest,
    OpdProbeEdlResponse,
    OpdResetEdlRequest,
    OpdResetEdlResponse,
    OpdScanEdlResponse,
    OpdStatusEdlRequest,
    OpdStatusEdlResponse,
    OpdSysEnableEdlRequest,
    OpdSysEnableEdlResponse,
    PingEdlRequest,
    PingEdlResponse,
    RtcSetTimeEdlRequest,
    TxControlEdlRequest,
    TxControlEdlResponse,
)
from ..subsystems.rtc import set_rtc_time, set_system_time_to_rtc_time
from .beacon import BeaconService
from .node_manager import NodeManagerService


class EdlCommandRunner:
    def __init__(
        self,
        node: ManagerNodeClient,
        node_mgr_service: NodeManagerService,
        beacon_service: BeaconService,
    ):
        self._node = node
        self._node_mgr_service = node_mgr_service
        self._beacon_service = beacon_service

        self._cmd_cbs = {
            EdlCommandId.TX_CONTROL: self.run_tx_control,
            EdlCommandId.C3_SOFT_RESET: self.run_soft_reset,
            EdlCommandId.C3_HARD_RESET: self.run_hard_reset,
            EdlCommandId.C3_FACTORY_RESET: self.run_factory_reset,
            EdlCommandId.CO_NODE_ENABLE: self.run_node_enable,
            EdlCommandId.CO_NODE_STATUS: self.run_node_status,
            EdlCommandId.CO_SDO_WRITE: self.run_sdo_write,
            EdlCommandId.CO_SYNC: self.run_sync,
            EdlCommandId.OPD_SYS_ENABLE: self.run_opd_sys_enable,
            EdlCommandId.OPD_SCAN: self.run_opd_scan,
            EdlCommandId.OPD_PROBE: self.run_opd_probe,
            EdlCommandId.OPD_ENABLE: self.run_opd_enable,
            EdlCommandId.OPD_RESET: self.run_opd_reset,
            EdlCommandId.OPD_STATUS: self.run_opd_status,
            EdlCommandId.RTC_SET_TIME: self.run_rtc_set_time,
            EdlCommandId.TIME_SYNC: self.run_time_sync,
            EdlCommandId.BEACON_PING: self.run_beacon_ping,
            EdlCommandId.PING: self.run_ping,
            EdlCommandId.RX_TEST: self.run_rx_test,
            EdlCommandId.CO_SDO_READ: self.run_sdo_read,
        }

    def run(self, request: EdlCommandRequest) -> EdlCommandResponse:
        cmd_id = EdlCommandId(request.id)

        args = astuple(request.payload) if request.payload else None
        logger.info(f"EDL command request: {cmd_id.name}, args: {args}")

        cmd_cb = self._cmd_cbs.get(cmd_id, None)
        if cmd_cb is None:
            raise ValueError(f"no callback for EDL command: {cmd_id.name}")

        res_payload = cmd_cb() if request is None else cmd_cb(request.payload)
        response = EdlCommandResponse(request.id, res_payload)

        values = astuple(response.payload) if response.payload else None
        logger.info(f"EDL command response: {cmd_id.name}, values: {values}")
        return response

    def run_tx_control(self, request: TxControlEdlRequest) -> TxControlEdlResponse:
        if request.enable is True:
            logger.info("EDL enabling Tx")
            self._node.od_write(C3Entry.TX_CONTROL_ENABLE, False)
            self._node.od_write(C3Entry.TX_CONTROL_LAST_ENABLE_TIMESTAMP, int(time()))
        else:
            logger.info("EDL disabling Tx")
            self._node.od_write(C3Entry.TX_CONTROL_ENABLE, True)
            self._node.od_write(C3Entry.TX_CONTROL_LAST_ENABLE_TIMESTAMP, 0)
        return TxControlEdlResponse(request.enable)

    def run_soft_reset(self) -> None:
        logger.info("EDL soft reset")
        self._node.od_write(C3Entry.SYSTEM_RESET, C3SystemReset.SOFT_RESET)

    def run_hard_reset(self) -> None:
        logger.info("EDL hard reset")
        self._node.od_write(C3Entry.SYSTEM_RESET, C3SystemReset.HARD_RESET)

    def run_factory_reset(self) -> None:
        logger.info("EDL factory reset")
        self._node.od_write(C3Entry.SYSTEM_RESET, C3SystemReset.FACTORY_RESET)

    def run_node_enable(self, request: CoNodeEnableEdlRequest) -> CoNodeEnableEdlResponse:
        card = Card.from_node_id(request.node_id)
        logger.info(f"EDL enabling CANopen node {card.name} (0x{request.node_id:02X})")
        self._node_mgr_service.enable(card, request.enable)
        return CoNodeEnableEdlResponse(self._node_mgr_service.status(card).value)

    def run_node_status(self, request: CoNodeStatusEdlRequest) -> CoNodeStatusEdlResponse:
        card = Card.from_node_id(request.node_id)
        logger.info(f"EDL getting CANopen node {card.name} (0x{request.node_id:02X}) status")
        return CoNodeStatusEdlResponse(self._node_mgr_service.status(card).value)

    def run_sdo_write(self, request: CoSdoWriteEdlRequest) -> CoSdoWriteEdlResponse:
        name = "C3" if request.node_id == 1 else Card.from_node_id(request.node_id).name
        logger.info(f"EDL SDO read on CANopen node {name} (0x{request.node_id:02X})")
        abort_code = 0
        try:
            if request.node_id == 1:
                entry = C3Entry.find(request.index, request.subindex)
                value = entry.decode(request.buffer)
                self._node.od_write(entry, value)
            else:
                self._node.sdo_write_raw(
                    request.node_id, request.index, request.subindex, request.buffer
                )
        except Exception as e:
            logger.error(e)
            abort_code = 0x06090011
        return CoSdoWriteEdlResponse(abort_code)

    def run_sync(self) -> None:
        logger.info("EDL sending CANopen SYNC message")
        self._node.send_sync()

    def run_opd_sys_enable(self, request: OpdSysEnableEdlRequest) -> OpdSysEnableEdlResponse:
        if request.enable:
            logger.info("EDL enabling OPD subsystem")
            self._node_mgr_service.opd.enable()
        else:
            logger.info("EDL disabling OPD subsystem")
            self._node_mgr_service.opd.disable()
        return OpdSysEnableEdlResponse(self._node_mgr_service.opd.status.value != 0)

    def run_opd_scan(self) -> OpdScanEdlResponse:
        logger.info("EDL scaning for all OPD nodes")
        return OpdScanEdlResponse(self._node_mgr_service.opd.scan())

    def run_opd_probe(self, request: OpdProbeEdlRequest) -> OpdProbeEdlResponse:
        card = Card.from_opd_address(request.opd_addr)
        logger.info(f"EDL probing for OPD node {card.name} (0x{card.opd_address:02X})")
        opd_node = self._node_mgr_service.opd[card.opd_address]
        return OpdProbeEdlResponse(opd_node.probe())

    def run_opd_enable(self, request: OpdEnableEdlRequest) -> OpdEnableEdlResponse:
        card = Card.from_opd_address(request.opd_addr)
        opd_node = self._node_mgr_service.opd[card.opd_address]
        if request.enable:
            logger.info(f"EDL enabling OPD node {card.name} (0x{card.opd_address:02X})")
            opd_node.enable()
        else:
            logger.info(f"EDL disabling OPD node {card.name} (0x{card.opd_address:02X})")
            opd_node.disable()
        return OpdEnableEdlResponse(opd_node.status.value)

    def run_opd_reset(self, request: OpdResetEdlRequest) -> OpdResetEdlResponse:
        card = Card.from_opd_address(request.opd_addr)
        logger.info(f"EDL resetting OPD node {card.name} (0x{card.opd_address:02X})")
        opd_node = self._node_mgr_service.opd[card.opd_address]
        opd_node.reset()
        return OpdResetEdlResponse(opd_node.status.value)

    def run_opd_status(self, request: OpdStatusEdlRequest) -> OpdStatusEdlResponse:
        card = Card.from_opd_address(request.opd_addr)
        logger.info(f"EDL getting the status for OPD node {card.name} (0x{card.opd_address:02X})")
        opd_node = self._node_mgr_service.opd[card.opd_address]
        return OpdStatusEdlResponse(opd_node.status.value)

    def run_rtc_set_time(self, request: RtcSetTimeEdlRequest) -> None:
        logger.info(f"EDL setting the RTC time to {request.time}")
        set_rtc_time(request.time)
        set_system_time_to_rtc_time()

    def run_time_sync(self) -> None:
        logger.info("EDL sending time sync TPDO")
        self._node.send_tpdo(0)

    def run_beacon_ping(self) -> None:
        logger.info("EDL beacon")
        self._beacon_service.send()

    def run_ping(self, request: PingEdlRequest) -> PingEdlResponse:
        logger.info(f"EDL ping {request.value}")
        return PingEdlResponse(request.value)

    def run_rx_test(self) -> None:
        logger.info("EDL Rx test")

    def run_sdo_read(self, request: CoSdoReadEdlRequest) -> CoSdoReadEdlResponse:
        name = "C3" if request.node_id == 1 else Card.from_node_id(request.node_id).name
        logger.info(f"EDL SDO read on CANopen node {name} (0x{request.node_id:02X})")
        raw = b""
        abort_code = 0
        try:
            if request.node_id == 1:
                entry = C3Entry.find(request.index, request.subindex)
                value = self._node.od_read(entry)
                raw = entry.encode(value)
            else:
                raw = self._node.sdo_read_raw(request.node_id, request.index, request.subindex)
        except Exception as e:
            logger.error(e)
            abort_code = 0x06090011
        return CoSdoReadEdlResponse(abort_code, raw)
