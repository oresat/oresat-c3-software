from __future__ import annotations

from queue import Empty, SimpleQueue
from time import monotonic

from ccsds_cop.cop_1 import ControlWord, CopService
from ccsds_cop.cop_1.farm import Farm1
from olaf import Service, logger
from spacepackets.uslp import TransferFrame
from spacepackets.uslp.defs import UslpChecksumError
from spacepackets.uslp.frame import FrameType
from spacepackets.uslp.header import SourceOrDestField

from .. import C3State
from ..protocols.edl_packet import EdlVcid
from ..protocols.uslp import make_frame, unpack_frame
from .cop_manager import CopManagerService
from .radios import RadiosService


class ChannelRouterService(Service):
    """Virtual Channel Router Service

    The router handles fetching raw data from the radios, unpacking frames, and finally places
    valid frames into the appropriate queue.
    """

    _CLCW_INTERVAL = 1.0

    def __init__(self, radios_service: RadiosService, cop_service: CopManagerService):
        super().__init__()
        self._radios_service = radios_service
        self._cop_service = cop_service
        self._uplink_routes: dict[EdlVcid, SimpleQueue[TransferFrame]] = {}
        self._downlink_routes: dict[EdlVcid, SimpleQueue[bytes]] = {}
        self._last_clcw_time = 0.0

    def on_start(self) -> None:
        self._send_clcws()

    def on_loop(self) -> None:
        for dl in self._downlink_routes.values():
            while True:
                try:
                    msg = dl.get_nowait()
                    self._radios_service.send_edl_response(msg)
                except Empty:  # noqa: PERF203
                    break

        if self.node.od["status"].value == C3State.EDL:
            now = monotonic()
            if now - self._last_clcw_time >= self._CLCW_INTERVAL:
                self._send_clcws()
                self._last_clcw_time = now

        try:
            message = self._radios_service.recv_queue.get(timeout=0.1)
        except Empty:
            return

        try:
            frame = unpack_frame(message)
            if frame.op_ctrl_field is not None:
                self._cop_service.dispatch_clcw(ControlWord.unpack(frame.op_ctrl_field))
            vcid = frame.header.vcid
            if vcid in self._uplink_routes:
                self._uplink_routes[vcid].put_nowait(frame)
            else:
                logger.error(f"No route for VCID {frame.header.vcid}")
        except UslpChecksumError as e:
            logger.error(f"Frame checksum error: {e}")
            logger.debug(message)
        except Exception as e:
            logger.exception(f"Failed to unpack frame: {e}")

    def _send_clcws(self) -> None:
        for clcw in self._get_all_clcw():
            frame = make_frame(
                payload=bytes(1),
                vcid=EdlVcid.IDLE,
                src_dest=SourceOrDestField.SOURCE,
                control_word=clcw.pack(),
            )
            self._radios_service.send_edl_response(
                frame.pack(frame_type=FrameType.VARIABLE)
            )

    def request_uplink_route(
        self, vcid: EdlVcid, use_cop: bool = False
    ) -> SimpleQueue[TransferFrame]:
        """Request an uplink Virtual Channel route.

        Parameters
        ----------
        vcid
            The VCID used to identify the route.
        use_cop
            True enables COP-1 (FARM-1) on this route.

        Returns
        -------
        SimpleQueue[TransferFrame]
            The queue from which received uplink frames for the VCID may be fetched.

        Raises
        ------
        KeyError
            A route for `vcid` has already been claimed.
        """
        if vcid in self._uplink_routes:
            raise KeyError(f"Uplink route for VCID={vcid} already exists")
        if use_cop:
            q = self._cop_service.create_farm_service(vcid)
            self._uplink_routes[vcid] = self._cop_service.recv_queue
        else:
            q = SimpleQueue()
            self._uplink_routes[vcid] = q
        return q

    def request_downlink_route(self, vcid: EdlVcid) -> SimpleQueue[bytes]:
        """Request a downlink Virtual Channel route.

        Parameters
        ----------
        vcid
            The VCID used to identify the route.

        Returns
        -------
        SimpleQueue[bytes]
            A queue to place packed frames for downlinking.

        Raises
        ------
        KeyError
            A route for `vcid` has already been claimed.
        """

        if vcid in self._downlink_routes:
            raise KeyError(f"Downlink route for VCID={vcid} already exists")
        else:
            q: SimpleQueue[bytes] = SimpleQueue()
            self._downlink_routes[vcid] = q
            logger.info(f"Created downlink route for VCID {vcid}")
            return q

    def _get_all_clcw(self) -> list[ControlWord]:
        clcws = []
        for v in self._uplink_routes.keys():
            srv: CopService | None = self._cop_service.get_service(v)
            if isinstance(srv, Farm1):
                clcws.append(
                    ControlWord(
                        vcid=v,
                        lockout=srv.lockout,
                        wait=srv.wait,
                        retransmit=srv.retransmit,
                        farm_b_counter=srv.b_counter,
                        report_value=srv.v_r,
                    )
                )
        return clcws
