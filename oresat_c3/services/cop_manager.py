from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import Enum
from queue import Empty, SimpleQueue
from typing import Optional, TypeVar

from ccsds_cop.cop_1 import ControlWord, CopService, Gvcid
from ccsds_cop.cop_1.farm import (
    Farm1,
    FarmHigherServiceInterface,
    FduArrivedIndication,
    ValidFrameArrivedIndication,
)
from ccsds_cop.cop_1.fop import (
    AbortRequest,
    Alert,
    AsyncNotification,
    AsyncNotificationType,
    DirectiveNotification,
    Fop1,
    NotificationType,
    RequestToTransferFdu,
    ServiceType,
    TransferNotification,
    TransmitRequestForFrame,
)
from olaf import Service, logger
from spacepackets.uslp import (
    BypassSequenceControlFlag,
    ProtocolCommandFlag,
    SourceOrDestField,
    TransferFrame,
)
from spacepackets.uslp.frame import FrameType
from uslp import SPACECRAFT_ID, make_frame

from ..protocols.edl_packet import EdlVcid

T = TypeVar("T")


def _drain(getter: Callable[[], T], exc: type[BaseException]) -> Iterator[T]:
    try:
        while True:
            yield getter()
    except exc:
        return


class FopSupervisorState(Enum):
    IDLE = 0
    INITIATING = 1
    ACTIVE = 2
    RECOVERING = 3
    SUSPENDED = 4
    BD_FALLBACK = 5


@dataclass
class FopInstance:
    service: Fop1
    fdu_queue: SimpleQueue[bytes]
    send_queue: SimpleQueue[bytes]
    requests: set[int] = field(default_factory=set)
    state: FopSupervisorState = FopSupervisorState.IDLE
    _next_rid = 0
    _last_clcw: float = 0.0

    def next_rid(self) -> int:
        rid = self._next_rid
        self._next_rid += 1
        return rid


class CopManagerService(Service):
    """COP-1 Services Manager
    This service acts as both the Higher and Lower procedures for any number of FARM-1
    or FOP-1 COP-1 services
    """

    def __init__(self) -> None:
        super().__init__()
        self._farms: dict[EdlVcid, tuple[CopService, SimpleQueue[TransferFrame]]] = {}
        self._fops: dict[EdlVcid, FopInstance] = {}
        self._clcw_queue: SimpleQueue[ControlWord] = SimpleQueue()
        self.recv_queue: SimpleQueue[TransferFrame] = SimpleQueue()

    def on_loop(self) -> None:
        self._process_farm_higher()
        self._process_farm_lower()
        self._process_clcw()
        self._process_fop_higher()
        self._process_fop_lower()
        self.sleep_ms(50)

    def _process_farm_lower(self) -> None:
        try:
            frame = self.recv_queue.get_nowait()
            srv, _ = self._farms.get(frame.header.vcid, (None, None))
            if srv is not None:
                if srv.lower_interface.buffer.try_appendleft(frame):
                    srv.lower_interface.signal.try_appendleft(
                        ValidFrameArrivedIndication(
                            Gvcid(0b1100, frame.header.scid, frame.header.vcid)
                        )
                    )
                    srv.tick()
                else:
                    logger.warning(f"FARM VCID={frame.header.vcid}: buffer full")
        except Empty:
            pass

    def _process_farm_higher(self) -> None:
        for srv, q in self._farms.values():
            hi: FarmHigherServiceInterface = srv.higher_interface
            try:
                sig = hi.signal.pop()
                if isinstance(sig, FduArrivedIndication):
                    q.put_nowait(hi.buffer.pop())
                    hi.buffer_release.set()
            except IndexError:
                continue

    def _process_fop_lower(self) -> None:
        for instance in self._fops.values():
            for i in _drain(instance.service.interface.to_lower.pop, IndexError):
                if isinstance(i, TransmitRequestForFrame):
                    fr = make_frame(
                        payload=i.tfdf,
                        vcid=i.gvcid.vcid,
                        src_dest=SourceOrDestField.SOURCE,
                        vcf_count=i.v_s
                        if i.bypass_flag == BypassSequenceControlFlag.SEQ_CTRLD_QOS
                        else None,
                        bypass=i.bypass_flag == BypassSequenceControlFlag.EXPEDITED_QOS,
                        command=i.command_flag == ProtocolCommandFlag.PROTOCOL_INFORMATION,
                    )
                    instance.send_queue.put_nowait(fr.pack(FrameType.VARIABLE))
                elif isinstance(i, AbortRequest):
                    # TODO: if anything is being processed for the GVCID, abort them
                    pass
                else:
                    logger.error(f"Unknown FOP-1 Lower Procedures request of type {type(i)}")

    def _process_fop_higher(self) -> None:
        for vcid, instance in self._fops.items():
            instance.service.drain_timer_events()
            for fdu in _drain(instance.fdu_queue.get_nowait, Empty):
                instance.service.on_receive_request_to_transfer_fdu(
                    RequestToTransferFdu(
                        gvcid=Gvcid(0b1100, SPACECRAFT_ID, vcid),
                        request_id=instance.next_rid(),
                        fdu=fdu,
                        service_type=ServiceType.BD
                        if instance.state == FopSupervisorState.BD_FALLBACK
                        else ServiceType.AD,
                    ),
                )
            for i in _drain(instance.service.interface.to_higher.pop, IndexError):
                if isinstance(i, DirectiveNotification):
                    if i.notification_type == NotificationType.ACCEPT:
                        instance.requests.add(i.request_id)
                    elif i.notification_type == NotificationType.REJECT:
                        # TODO: notify the user
                        instance.requests.remove(i.request_id)
                    elif i.notification_type == NotificationType.POSITIVE_CONFIRM:
                        if instance.state == FopSupervisorState.RECOVERING:
                            instance.state = FopSupervisorState.ACTIVE
                        instance.requests.remove(i.request_id)
                    elif i.notification_type == NotificationType.NEGATIVE_CONFIRM:
                        # TODO: notify the user, note: an alert will always be received before
                        #  NEGATIVE_CONFIRM
                        instance.requests.remove(i.request_id)
                elif isinstance(i, AsyncNotification):
                    if i.notification_type == AsyncNotificationType.ALERT:
                        self._recover(instance, i.notification_qualifier)
                elif isinstance(i, TransferNotification):
                    if i.notification_type == NotificationType.ACCEPT:
                        pass
                    elif i.notification_type == NotificationType.REJECT:
                        pass
                    elif i.notification_type == NotificationType.POSITIVE_CONFIRM:
                        pass
                    elif i.notification_type == NotificationType.NEGATIVE_CONFIRM:
                        pass

    def _process_clcw(self) -> None:
        for clcw in _drain(self._clcw_queue.get_nowait, Empty):
            instance = self._fops.get(EdlVcid(clcw.vcid))
            if instance is not None:
                if instance.state in (FopSupervisorState.IDLE, FopSupervisorState.SUSPENDED):
                    # TODO: send INITIATE_AD_WITH_SET_V_R directive
                    instance.state = FopSupervisorState.INITIATING
                instance.service.on_clcw_arrived(clcw)
            else:
                logger.error(f"Received invalid VCID in CLCW: {clcw.vcid}")

    def _recover(self, instance: FopInstance, alert: Alert) -> None:
        instance.state = FopSupervisorState.RECOVERING
        if alert == Alert.LOCKOUT:
            pass  # init ad with unlock
        elif alert in (Alert.SYNCH, Alert.NNR, Alert.CLCW):
            pass  # init ad with set vr (from last CLCW)
        elif alert in (Alert.LIMIT, Alert.T1, Alert.LLIF):
            pass  # init with clcw
        elif alert == Alert.TERM:
            # unrecoverable: go to IDLE
            instance.state = FopSupervisorState.IDLE

    def create_farm_service(self, vcid: EdlVcid) -> SimpleQueue[TransferFrame]:
        logger.info(f"Creating FARM-1 Service for VCID {vcid}")
        q: SimpleQueue[TransferFrame] = SimpleQueue()
        self._farms[vcid] = (Farm1(w=20, vcf_count_length=1), q)
        return q

    def create_fop_service(
        self, vcid: EdlVcid, send_queue: SimpleQueue[bytes]
    ) -> SimpleQueue[bytes]:
        """Create a FOP-1 Service for a VCID.

        Parameters
        ----------
        vcid
            The VCID to assoociate with the FOP-1 Service.
        send_queue
            The queue into which FOP-1 will place frames assembled by the Lower Procedures.

        Returns
        -------
        SimpleQueue[bytes]
            A queue of FDUs for FOP-1.
        """
        logger.info(f"Creating FOP-1 Service for VCID {vcid}")
        q: SimpleQueue[bytes] = SimpleQueue()
        self._fops[vcid] = FopInstance(
            service=Fop1(Gvcid(0b1100, SPACECRAFT_ID, vcid)),
            fdu_queue=q,
            send_queue=send_queue,
        )
        return q

    def dispatch_clcw(self, clcw: ControlWord) -> None:
        """Hand a control word to the COP Manager for automatic routing to a FOP-1 instance."""
        self._clcw_queue.put_nowait(clcw)

    def get_service(self, vcid: EdlVcid) -> Optional[CopService]:
        entry = self._farms.get(vcid)
        if entry is not None:
            return entry[0]
        else:
            return entry
