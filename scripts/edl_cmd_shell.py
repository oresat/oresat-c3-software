#!/usr/bin/env python3
"""Quick shell to manually send EDL commands."""

import os
import socket
import sys
from argparse import ArgumentParser
from cmd import Cmd
from time import time
from typing import Any, Union

import canopen
from ccsds_cop.cop_1 import ControlWord, Gvcid
from ccsds_cop.cop_1.fop import (
    AsyncNotification,
    AsyncNotificationType,
    DirectiveNotification,
    DirectiveRequest,
    DirectiveType,
    Fop1,
    FopState,
    NotificationType,
    RequestToTransferFdu,
    Response,
    ResponseType,
    ServiceType,
    TransmitRequestForFrame,
)
from oresat_configs import Mission, OreSatConfig
from spacepackets.uslp import BypassSequenceControlFlag, ProtocolCommandFlag
from spacepackets.uslp.defs import UslpInvalidRawPacketOrFrameLenError
from spacepackets.uslp.frame import FrameType

from oresat_c3.protocols.uslp import SPACECRAFT_ID, make_frame, unpack_frame

sys.path.insert(0, os.path.abspath(".."))

from oresat_c3.protocols.edl_command import EDL_COMMANDS, EdlCommandCode, EdlCommandRequest
from oresat_c3.protocols.edl_packet import SRC_DEST_ORESAT, EdlPacket, EdlVcid


class EdlCommandShell(Cmd):
    """Edl command shell for testing."""

    intro = "Welcome to the EDL shell. Type help or ? to list commands.\n"
    prompt = "> "

    def __init__(
        self, host: str, uplink_port: int, downlink_port: int, hmac_key: bytes, seq_num: int
    ):
        super().__init__()

        self.configs = OreSatConfig(Mission.default())
        self._hmac_key = hmac_key
        self._timeout = 5
        self._seq_num = seq_num

        self._uplink_address = (host, uplink_port)
        self._uplink_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        if host not in ["localhost", "127.0.0.1"]:
            host = ""

        self._downlink_address = (host, downlink_port)
        self._downlink_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._downlink_socket.bind(self._downlink_address)
        self._downlink_socket.settimeout(self._timeout)

        self._gvcid = Gvcid(tfvn=0xC, scid=SPACECRAFT_ID, vcid=EdlVcid.C3_COMMAND)
        self._fop1 = Fop1(self._gvcid, timer_initial_value=3)
        self._fop1_req_id = 0
        self._last_clcw: dict[int, ControlWord] = {}
        self._fop1.on_receive_directive(
            DirectiveRequest(self._gvcid, 0, DirectiveType.INITIATE_AD_NO_CLCW)
        )
        self._fop1.on_receive_response_from_lower_layer(
            Response(self._gvcid, ResponseType.AD_ACCEPTED)
        )

    def _flush_fop_lower(self) -> None:
        """Send any frames queued by FOP-1 to the uplink socket."""
        for queue in (self._fop1.interface.to_lower, self._fop1.lower_interface.signal):
            while True:
                try:
                    req = queue.pop()
                except IndexError:
                    break
                if not isinstance(req, TransmitRequestForFrame):
                    continue
                bypass = req.bypass_flag == BypassSequenceControlFlag.EXPEDITED_QOS
                frame = make_frame(
                    payload=req.tfdf,
                    vcid=EdlVcid.C3_COMMAND,
                    src_dest=SRC_DEST_ORESAT,
                    hmac_key=self._hmac_key,
                    sequence_number=self._seq_num,
                    vcf_count=None if bypass else req.v_s,
                    bypass=bypass,
                    command=req.command_flag == ProtocolCommandFlag.PROTOCOL_INFORMATION,
                )
                self._uplink_socket.sendto(
                    frame.pack(frame_type=FrameType.VARIABLE),
                    self._uplink_address,
                )

    def _process_clcw(self, clcw: ControlWord) -> None:
        """Feed a CLCW to FOP-1 and warn if the state machine falls back to INITIAL."""
        self._last_clcw[clcw.vcid] = clcw
        if clcw.vcid == self._gvcid.vcid:
            self._fop1.on_clcw_arrived(clcw)
            self._flush_fop_lower()
            while True:
                try:
                    notif = self._fop1.interface.to_higher.pop()
                except IndexError:
                    break
                if (
                    isinstance(notif, AsyncNotification)
                    and notif.notification_type == AsyncNotificationType.ALERT
                ):
                    print(
                        f"FOP-1 alert: {notif.notification_qualifier.name} "
                        f"(state={self._fop1.state.name}, use 'cop_init' to reinitialize)"
                    )

    def _drain_clcws(self) -> None:
        """Drain any buffered CLCW frames from the socket without blocking."""
        self._downlink_socket.settimeout(0)
        try:
            while True:
                raw = self._downlink_socket.recv(1024)
                try:
                    frame = unpack_frame(raw)
                except UslpInvalidRawPacketOrFrameLenError:
                    continue
                if frame.header.vcid == EdlVcid.IDLE and frame.op_ctrl_field:
                    self._process_clcw(ControlWord.unpack(frame.op_ctrl_field))
        except (socket.timeout, BlockingIOError):
            pass
        finally:
            self._downlink_socket.settimeout(self._timeout)

    def _send_packet(self, code: EdlCommandCode, args: Union[tuple, None] = None) -> tuple:
        # processing cop sequentially is unusual, so we need to drain any CLCWs
        # from the previous command before the next frame to prevent timeouts
        self._drain_clcws()

        sequenced = self._fop1.state == FopState.ACTIVE
        print(
            f"Request {code.name}: {args} | seq_num: {self._seq_num}"
            f" | {'sequenced' if sequenced else 'expedited'}"
        )

        res_packet = None
        try:
            tfdz = EdlCommandRequest(code, args).pack()

            if sequenced:
                self._fop1_req_id += 1
                self._fop1.on_receive_request_to_transfer_fdu(
                    RequestToTransferFdu(self._gvcid, self._fop1_req_id, tfdz, ServiceType.AD)
                )
                self._flush_fop_lower()
            else:
                frame = make_frame(
                    payload=tfdz,
                    vcid=EdlVcid.C3_COMMAND,
                    src_dest=SRC_DEST_ORESAT,
                    hmac_key=self._hmac_key,
                    sequence_number=self._seq_num,
                    bypass=True,
                )
                self._uplink_socket.sendto(
                    frame.pack(frame_type=FrameType.VARIABLE),
                    self._uplink_address,
                )

            edl_command = EDL_COMMANDS[code]
            if edl_command.res_fmt is not None or edl_command.res_unpack_func is not None:
                try:
                    while True:
                        raw = self._downlink_socket.recv(1024)
                        try:
                            frame = unpack_frame(raw)
                        except UslpInvalidRawPacketOrFrameLenError:
                            continue
                        if frame.header.vcid == EdlVcid.IDLE and frame.op_ctrl_field:
                            self._process_clcw(ControlWord.unpack(frame.op_ctrl_field))
                            continue
                        if frame.header.vcid == EdlVcid.C3_COMMAND:
                            res_packet = EdlPacket.from_frame(frame, self._hmac_key)
                            break
                except socket.timeout:
                    raise TimeoutError("No C3_COMMAND response")
                if sequenced and self._fop1.nn_r != self._fop1.v_s:
                    self._downlink_socket.settimeout(self._fop1.timer_initial_value)
                    try:
                        while (
                            self._fop1.nn_r != self._fop1.v_s
                            and self._fop1.state == FopState.ACTIVE
                        ):
                            try:
                                raw = self._downlink_socket.recv(1024)
                            except socket.timeout:
                                break
                            try:
                                frame = unpack_frame(raw)
                            except UslpInvalidRawPacketOrFrameLenError:
                                continue
                            if frame.header.vcid == EdlVcid.IDLE and frame.op_ctrl_field:
                                self._process_clcw(ControlWord.unpack(frame.op_ctrl_field))
                    finally:
                        self._downlink_socket.settimeout(self._timeout)
            elif sequenced:
                # no EDL response expected, wait for CLCW to acknowledge the AD frame
                for _ in range(10):
                    try:
                        raw = self._downlink_socket.recv(1024)
                    except socket.timeout:
                        break
                    try:
                        frame = unpack_frame(raw)
                    except UslpInvalidRawPacketOrFrameLenError:
                        continue
                    if frame.header.vcid == EdlVcid.IDLE and frame.op_ctrl_field:
                        self._process_clcw(ControlWord.unpack(frame.op_ctrl_field))
                        if self._fop1.nn_r == self._fop1.v_s:
                            break

            if sequenced:
                self._fop1.on_receive_response_from_lower_layer(
                    Response(self._gvcid, ResponseType.AD_ACCEPTED)
                )
            self._seq_num += 1
        except Exception as e:  # pylint: disable=W0718
            print(e)
            return ()

        ret = None
        if res_packet and res_packet.payload.values:
            ret = res_packet.payload.values
            print(f"Response {code.name}: {ret}")

        return ret

    def help_cop_status(self):
        """Print help message for cop_status command."""
        print("cop_status")
        print("  print FOP-1 state and last known CLCWs")

    def do_cop_status(self, _):
        """Print FOP-1 state and last known CLCWs."""
        self._drain_clcws()
        fop = self._fop1
        print(f"FOP-1 state : {fop.state.name}")
        print(f"  V(S)      = {fop.v_s}")
        print(f"  NN(R)     = {fop.nn_r}")
        print(f"  ad_out    = {fop.ad_out}")
        print(f"  sent queue= {len(fop._sent_queue)}")  # pylint: disable=W0212
        if self._last_clcw:
            print("Last CLCWs:")
            for vcid, clcw in sorted(self._last_clcw.items()):
                print(
                    f"  VCID {vcid}: V(R)={clcw.report_value}"
                    f"  lockout={clcw.lockout}"
                    f"  wait={clcw.wait}"
                    f"  retransmit={clcw.retransmit}"
                    f"  farm_b={clcw.farm_b_counter}"
                )
        else:
            print("No CLCWs received yet")

    def help_cop_resume(self):
        """Print help message for cop_resume command."""
        print("cop_resume")
        print("  resume a suspended FOP-1 AD service")

    def do_cop_resume(self, _):
        """Resume a suspended FOP-1 AD service."""
        if self._fop1.suspend_state == 0:
            print("FOP-1 is not suspended")
            return
        self._fop1_req_id += 1
        self._fop1.on_receive_directive(
            DirectiveRequest(self._gvcid, self._fop1_req_id, DirectiveType.RESUME_AD)
        )
        try:
            while True:
                self._fop1.interface.to_higher.pop()
        except IndexError:
            pass
        print(f"FOP-1 resumed: state={self._fop1.state.name}, V(S)={self._fop1.v_s}")

    def help_cop_terminate(self):
        """Print help message for cop_terminate command."""
        print("cop_terminate")
        print("  terminate FOP-1 AD service. Subsequent commands are sent expedited")

    def do_cop_terminate(self, _):
        """Terminate FOP-1 AD service."""
        self._fop1_req_id += 1
        self._fop1.on_receive_directive(
            DirectiveRequest(self._gvcid, self._fop1_req_id, DirectiveType.TERMINATE_AD)
        )
        try:
            while True:
                self._fop1.interface.to_higher.pop()
        except IndexError:
            pass
        print(f"FOP-1 terminated: state={self._fop1.state.name}")

    def help_cop_init(self):
        """Print help message for cop_init command."""
        print("cop_init [v_r]")
        print("  reinitialize FOP-1 AD mode, waiting for CLCW confirmation")
        print("  no args: INITIATE_AD_WITH_CLCW — if V(S)!=V(R), SET_V_S first, then sync")
        print("  <v_r>:   INITIATE_AD_WITH_SET_V_R — send BC frame to set FARM-1 V(R) to <v_r>")

    def do_cop_init(self, arg: str):
        """Reinitialize FOP-1 AD mode, blocking until CLCW confirms ACTIVE."""
        if self._fop1.suspend_state != 0:
            print("FOP-1 is suspended; use 'cop_resume' before reinitializing")
            return
        self._fop1_req_id += 1
        self._fop1.on_receive_directive(
            DirectiveRequest(self._gvcid, self._fop1_req_id, DirectiveType.TERMINATE_AD)
        )
        try:
            while True:
                self._fop1.interface.to_higher.pop()
        except IndexError:
            pass

        if arg.strip():
            v_r = int(arg.strip(), 0)
            # force bc_out=True so FOP-1 can send the BC frame
            self._fop1.on_receive_response_from_lower_layer(
                Response(self._gvcid, ResponseType.BC_ACCEPTED)
            )
            directive = DirectiveRequest(
                self._gvcid, self._fop1_req_id, DirectiveType.INITIATE_AD_WITH_SET_V_R, v_r
            )
        else:
            self._drain_clcws()
            last = self._last_clcw.get(self._gvcid.vcid)
            target_v_s = last.report_value if last is not None else self._fop1.v_s
            if target_v_s != self._fop1.v_s or self._fop1.nn_r != self._fop1.v_s:
                self._fop1_req_id += 1
                self._fop1.on_receive_directive(
                    DirectiveRequest(
                        self._gvcid,
                        self._fop1_req_id,
                        DirectiveType.SET_V_S,
                        target_v_s,
                    )
                )
                try:
                    while True:
                        self._fop1.interface.to_higher.pop()
                except IndexError:
                    pass
            directive = DirectiveRequest(
                self._gvcid, self._fop1_req_id, DirectiveType.INITIATE_AD_WITH_CLCW
            )
        self._fop1_req_id += 1
        self._fop1.on_receive_directive(directive)
        self._flush_fop_lower()

        while True:
            try:
                notif = self._fop1.interface.to_higher.pop()
            except IndexError:
                break
            if isinstance(notif, DirectiveNotification):
                if notif.notification_type == NotificationType.REJECT:
                    print(f"FOP-1 init rejected (state={self._fop1.state.name})")
                    return

        for _ in range(10):
            try:
                raw = self._downlink_socket.recv(1024)
            except socket.timeout:
                print("Timeout: no CLCW confirmation received")
                return
            try:
                frame = unpack_frame(raw)
            except UslpInvalidRawPacketOrFrameLenError:
                continue
            if frame.header.vcid != EdlVcid.IDLE or not frame.op_ctrl_field:
                continue
            clcw = ControlWord.unpack(frame.op_ctrl_field)
            self._last_clcw[clcw.vcid] = clcw
            if clcw.vcid != self._gvcid.vcid:
                continue
            self._fop1.on_clcw_arrived(clcw)
            self._flush_fop_lower()
            while True:
                try:
                    notif = self._fop1.interface.to_higher.pop()
                except IndexError:
                    break
                if isinstance(notif, DirectiveNotification):
                    if notif.notification_type == NotificationType.POSITIVE_CONFIRM:
                        print(
                            f"FOP-1 initialized: state={self._fop1.state.name},"
                            f" V(S)={self._fop1.v_s}"
                        )
                    else:
                        print(
                            f"FOP-1 init failed (state={self._fop1.state.name}, "
                            "use 'cop_init' to retry)"
                        )
                    return
                if (
                    isinstance(notif, AsyncNotification)
                    and notif.notification_type == AsyncNotificationType.ALERT
                ):
                    print(
                        f"FOP-1 alert: {notif.notification_qualifier.name} "
                        f"(state={self._fop1.state.name}, use 'cop_init' to retry)"
                    )
                    return
        print("No CLCW confirmation received")

    def help_tx_control(self):
        """Print help message for tx control command."""
        print("tx_control <bool>")
        print("  where <bool> is to disable or enable tx. Supports true/false/1/0")

    def do_tx_control(self, arg: str):
        """Do the tx control command."""

        args = arg.split(" ")
        if not arg or len(args) != 1:
            self.help_tx_control()
            return

        arg0 = args[0].lower()
        if arg0 in ["true", "1"]:
            value = True
        elif arg0 in ["false", "0"]:
            value = False
        else:
            self.help_tx_control()
            return

        self._send_packet(EdlCommandCode.TX_CTRL, (value,))

    def help_beacon_ping(self):
        """Print help message for beacon ping command."""
        print("beacon_ping")
        print("  no args")

    def do_beacon_ping(self, _):
        """Do the beacon ping command."""

        self._send_packet(EdlCommandCode.BEACON_PING, None)

    def help_ping(self):
        """Print help message for ping command."""
        print("ping <number>")
        print("  where <number> is a uint32 number or the word 'time' for a unix timestamp")

    def do_ping(self, arg: str):
        """Do the ping command."""

        args = arg.split(" ")
        if len(args) != 1:
            self.help_ping()
            return

        arg0 = args[0]
        if arg0 in ["", "time"]:
            value = int(time())
        elif arg0.startswith("0x"):
            value = int(arg0, 16)
        else:
            value = int(arg0)

        self._send_packet(EdlCommandCode.PING, (value,))

    def help_rx_test(self):
        """Print help message for rx_test command."""
        print("rx_test")
        print("  no args")

    def do_rx_test(self, _):
        """Do the rx_test command."""

        self._send_packet(EdlCommandCode.RX_TEST, None)

    def help_sdo_read(self):
        """Print help message for sdo_read command."""
        print("sdo_read <node> <index> <subindex>")
        print("  <node> is the node id or node name")
        print("  <index> is the index or object name")
        print("  <subindex> is the subindex or object name")

    def do_sdo_read(self, arg: str):
        """Do the sdo_read command."""

        args = arg.split(" ")
        if len(args) != 3:
            self.help_sdo_read()
            return

        node_id = None
        index = None
        subindex = None

        if args[0].startswith("0x"):
            node_id = int(args[0], 16)
            for i in self.configs.cards:
                if node_id == i.node_id:
                    name = i
                    break
        elif args[0] in self.configs.cards:
            name = args[0]
            node_id = self.configs.cards[args[0]].node_id
        else:
            print("invalid node arg")
            return

        od = self.configs.od_db[name]

        if args[1].startswith("0x"):
            index = int(args[1], 16)
        else:
            try:
                index = od[args[1]].index
            except Exception:  # pylint: disable=W0718
                print("invalid index arg")
                return

        if args[2].startswith("0x"):
            subindex = int(args[2], 16)
        else:
            try:
                if isinstance(od[index], canopen.objectdictionary.Variable):
                    subindex = 0
                else:
                    subindex = od[args[1]][args[2]].subindex
            except Exception:  # pylint: disable=W0718
                print("invalid subindex arg")
                return

        respone = self._send_packet(EdlCommandCode.CO_SDO_READ, (node_id, index, subindex))

        if not respone:
            return

        # response tuple: (node_id, index, subindex, ecode, len_data, data)
        if respone[3] != 0:
            print(f"SDO error code: 0x{respone[3]:08X}")
            return

        if isinstance(od[index], canopen.objectdictionary.Variable):
            obj = od[index]
        else:
            obj = od[index][subindex]
        value = obj.decode_raw(respone[5])
        print("Value from SDO read: ", value)

    def help_sdo_write(self):
        """Print help message for sdo_write command."""
        print("sdo_write <node> <index> <subindex> <value>")
        print("  <node> is the node id or node name")
        print("  <index> is the index or object name")
        print("  <subindex> is the subindex or object name")
        print("  <value> is value to write")
        print()
        print("If <index>.<subindex> is of type DOMAIN, <value> will be interpreted as a filename")
        print("and the contents will be written.")

    def do_sdo_write(self, arg: str):
        """Do the sdo_write command."""

        args = arg.split(" ", maxsplit=3)
        if len(args) != 4:
            self.help_sdo_write()
            return

        node_id = None
        index = None
        subindex = None

        if args[0].startswith("0x"):
            node_id = int(args[0], 16)
            for i in self.configs.cards:
                if node_id == i.node_id:
                    name = i
                    break
        elif args[0] in self.configs.cards:
            name = args[0]
            node_id = self.configs.cards[args[0]].node_id
        else:
            print("invalid node arg")
            return

        od = self.configs.od_db[name]

        if args[1].startswith("0x"):
            index = int(args[1], 16)
        else:
            try:
                index = od[args[1]].index
            except Exception:  # pylint: disable=W0718
                print("invalid index arg")
                return

        if args[2].startswith("0x"):
            subindex = int(args[2], 16)
        else:
            try:
                if isinstance(od[index], canopen.objectdictionary.Variable):
                    subindex = 0
                else:
                    subindex = od[args[1]][args[2]].subindex
            except Exception:  # pylint: disable=W0718
                print("invalid subindex arg")
                return

        if isinstance(od[index], canopen.objectdictionary.Variable):
            obj = od[index]
        else:
            obj = od[index][subindex]

        value: Any = None
        if obj.data_type == canopen.objectdictionary.BOOLEAN:
            value = args[3].lower() == "true"
        elif obj.data_type in canopen.objectdictionary.INTEGER_TYPES:
            value = int(args[3], 16) if args[3].startswith("0x") else int(args[3])
        elif obj.data_type in canopen.objectdictionary.FLOAT_TYPES:
            value = float(args[3])
        elif obj.data_type == canopen.objectdictionary.VISIBLE_STRING:
            value = args[3]
        elif obj.data_type == canopen.objectdictionary.DOMAIN:
            try:
                with open(args[3], "rb") as f:
                    value = f.read()
            except FileNotFoundError as e:
                print(f"{e.__class__.__name__}: {e}")
                return
        elif obj.data_type == canopen.objectdictionary.OCTET_STRING:
            try:
                value = bytes.fromhex(args[3])
            except ValueError:
                value = args[3].encode("ascii")

        else:
            print(f"invalid OD obj type {obj} 0x{obj.data_type:X}")
            return

        raw = obj.encode_raw(value)
        respone = self._send_packet(
            EdlCommandCode.CO_SDO_WRITE, (node_id, index, subindex, len(raw), raw)
        )

        if respone and respone[0] != 0:
            print(f"SDO error code: 0x{respone[0]:08X}")

    def help_c3_soft_reset(self):
        """Print help message for c3_soft_reset command."""
        print("c3_soft_reset")
        print("  no args")

    def do_c3_soft_reset(self, _):
        """Do the c3_soft_reset command."""

        self._send_packet(EdlCommandCode.C3_SOFT_RESET, None)

    def help_c3_hard_reset(self):
        """Print help message for c3_hard_reset command."""
        print("c3_hard_reset")
        print("  no args")

    def do_c3_hard_reset(self, _):
        """Do the c3_hard_reset command."""

        self._send_packet(EdlCommandCode.C3_HARD_RESET, None)

    def help_c3_factory_reset(self):
        """Print help message for c3_factory_reset command."""
        print("c3_factory_reset")
        print("  no args")

    def do_c3_factory_reset(self, _):
        """Do the c3_factory_reset command."""

        self._send_packet(EdlCommandCode.C3_FACTORY_RESET, None)

    def help_opd_sysenable(self):
        """Print help message for opd_sysenable command."""
        print("opd_sysenable <enable>")
        print("  <enable> is 0, 1, true, false")

    def do_opd_sysenable(self, arg: str):
        """Do the opd_sysenable command."""

        arg = arg.lower()
        if arg in ["true", "1"]:
            enable = True
        elif arg in ["false", "0"]:
            enable = False
        else:
            self.help_opd_sysenable()
            return

        self._send_packet(EdlCommandCode.OPD_SYSENABLE, (enable,))

    def help_opd_enable(self):
        """Print help message for opd_enable command."""
        print("opd_enable <name> <enable>")
        print("  <name> is the name of card or opd address in hex")
        print("  <enable> is 0, 1, true, false")

    def do_opd_enable(self, arg: str):
        """Do the opd_enable command."""

        args = arg.split(" ")
        if len(args) != 2:
            self.help_opd_enable()
            return

        if args[0].startswith("0x"):
            opd_addr = int(args[0], 16)
        else:
            opd_addr = 0
            for name, card in self.configs.cards.items():
                if name == args[0]:
                    opd_addr = card.opd_address
                    break
            if opd_addr == 0:
                print("invalid name / address")
                self.help_opd_enable()
                return

        arg1 = args[1].lower()
        if arg1 in ["true", "1"]:
            enable = True
        elif arg1 in ["false", "0"]:
            enable = False
        else:
            print("invalid enable value")
            self.help_opd_enable()
            return

        self._send_packet(EdlCommandCode.OPD_ENABLE, (opd_addr, enable))

    def help_rtc_set_time(self):
        """Print help message for rtc_set_time command."""
        print("rtc_set_time <number>")
        print(
            "  where <number> is unix time in seconds or the word 'now' to use the local system "
            "time"
        )

    def do_rtc_set_time(self, arg: str):
        """Do the rtc_set_time command."""

        args = arg.split(" ")
        if len(args) != 1:
            self.help_rtc_set_time()
            return

        arg0 = args[0]
        if arg0 in ["", "now"]:
            value = int(time())
        else:
            value = int(arg0)

        self._send_packet(EdlCommandCode.RTC_SET_TIME, (value,))

    def help_node_flash(self):
        """Print help message for node_flash command."""
        print(
            "node_flash <node> <filename>"
            "[throttle_delay] [block_transfer] [request_crc] [confirm_image]"
        )
        print("  <node> is the node id (e.g. 0x7C or 42) or node name")
        print("  <filename> is the name of the bin file in the C3 cache to flash")
        print("  [throttle_delay] is an optional delay between packets in seconds (default: 0.0)")
        print("  [block_transfer] is optional (true/false, 1/0) for block download (default: true)")
        print(
            "  [request_crc] is optional (true/false, 1/0) to request a CRC check (default: true)"
        )
        print(
            "  [confirm_image] is optional (true/false, 1/0) to confirm the image on boot "
            "(default: false)"
        )

    def do_node_flash(self, arg: str):
        """Do the node_flash command."""

        args = arg.split()
        if len(args) < 2 or len(args) > 6:
            self.help_node_flash()
            return

        node_id = None

        if args[0].startswith("0x"):
            node_id = int(args[0], 16)
        elif args[0] in self.configs.cards:
            node_id = self.configs.cards[args[0]].node_id
        else:
            try:
                node_id = int(args[0])
            except ValueError:
                print("invalid node arg. Must be hex, int, or valid card name.")
                return

        filename = args[1]

        throttle_delay = 0.0
        block_transfer = True
        request_crc = False
        confirm_image = False

        if len(args) >= 3:
            try:
                throttle_delay = float(args[2])
            except ValueError:
                print("invalid throttle_delay arg. Must be a float.")
                return

        if len(args) >= 4:
            arg3 = args[3].lower()
            if arg3 in ["true", "1", "t", "y", "yes"]:
                block_transfer = True
            elif arg3 in ["false", "0", "f", "n", "no"]:
                block_transfer = False
            else:
                print("invalid block_transfer arg. Must be true/false or 1/0.")
                return

        if len(args) >= 5:
            arg4 = args[4].lower()
            if arg4 in ["true", "1", "t", "y", "yes"]:
                request_crc = True
            elif arg4 in ["false", "0", "f", "n", "no"]:
                request_crc = False
            else:
                print("invalid request_crc arg. Must be true/false or 1/0.")
                return

        if len(args) >= 6:
            arg5 = args[5].lower()
            if arg5 in ["true", "1", "t", "y", "yes"]:
                confirm_image = True
            elif arg5 in ["false", "0", "f", "n", "no"]:
                confirm_image = False
            else:
                print("invalid confirm_image arg. Must be true/false or 1/0.")
                return

        response = self._send_packet(
            EdlCommandCode.CO_NODE_FLASH,
            (node_id, filename, throttle_delay, block_transfer, request_crc, confirm_image),
        )
        if response is not None:
            print(f"Flash command sent. Response: {response}")


def main():
    """Main for EDL shell script"""
    parser = ArgumentParser("Send a EDL command via socket")
    parser.add_argument(
        "-o", "--host", default="localhost", help="address to use, default is localhost"
    )
    parser.add_argument(
        "-u",
        "--uplink-port",
        default=10025,
        type=int,
        help="port to use for the uplink, default is 10025",
    )
    parser.add_argument(
        "-d",
        "--downlink-port",
        default=10016,
        type=int,
        help="port to use for the downlink, default is 10016",
    )
    parser.add_argument(
        "-n",
        "--sequence-number",
        type=int,
        default=0,
        help="edl sequence number, default 0",
    )
    parser.add_argument(
        "-m",
        "--hmac",
        default="",
        help="edl hmac, must be 32 bytes, default all zero",
    )
    args = parser.parse_args()

    if args.hmac:
        if len(args.hmac) != 64:
            print("Invalid hmac, must be hex string of 32 bytes")
            sys.exit(1)
        else:
            hmac_key = bytes.fromhex(args.hmac)
    else:
        hmac_key = b"\x00" * 32

    shell = EdlCommandShell(
        args.host, args.uplink_port, args.downlink_port, hmac_key, args.sequence_number
    )

    try:
        shell.cmdloop()
    except KeyboardInterrupt:
        pass

    print(f"last sequence number: {shell._seq_num}")  # pylint: disable=W0212


if __name__ == "__main__":
    main()
