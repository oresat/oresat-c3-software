from dataclasses import dataclass, field
from queue import Empty, SimpleQueue
from typing import Optional

from ccsds_cop.cop_1 import CopService, Gvcid
from ccsds_cop.cop_1.farm import (
    Farm1,
    FarmHigherServiceInterface,
    FduArrivedIndication,
    ValidFrameArrivedIndication,
)
from ccsds_cop.cop_1.fop import (
    AbortRequest,
    AsyncNotification,
    AsyncNotificationType,
    DirectiveNotification,
    Fop1,
    NotificationType,
    TransferNotification,
    TransmitRequestForFrame,
)
from olaf import Service, logger
from spacepackets.uslp import SourceOrDestField, TransferFrame
from uslp import make_frame

from ..protocols.edl_packet import EdlVcid


@dataclass
class FopInstance:
    service: Fop1
    recv_queue: SimpleQueue[TransferFrame] = field(default_factory=SimpleQueue)
    requests: dict[int, bool] = field(default_factory=dict)
    _next_rid = 0

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
        self.recv_queue: SimpleQueue[TransferFrame] = SimpleQueue()

    def on_loop(self) -> None:
        self._process_farm_higher()
        self._process_farm_lower()
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
        for srv, q in self._fops.values():
            i = srv.interface.to_lower.pop()
            if isinstance(i, TransmitRequestForFrame):
                fr = make_frame(
                    payload=i.tfdf,
                    vcid=i.gvcid.vcid,
                    src_dest=SourceOrDestField.SOURCE,
                    vcf_count=i.v_s,
                )
                q.put_nowait(fr)
            elif isinstance(i, AbortRequest):
                # TODO: if anything is being processed for the GVCID, abort them
                pass
            else:
                logger.error(f"Unknown FOP-1 Lower Procedures request of type {type(i)}")

    def _process_fop_higher(self) -> None:
        for instance in self._fops.values():
            try:
                i = instance.service.interface.to_higher.pop()
            except IndexError:
                continue
            if isinstance(i, DirectiveNotification):
                if i.notification_type == NotificationType.ACCEPT:
                    instance.requests[i.request_id] = True
                elif i.notification_type == NotificationType.REJECT:
                    # TODO: notify the user
                    del instance.requests[i.request_id]
                elif i.notification_type == NotificationType.POSITIVE_CONFIRM:
                    # TODO: notify user of completion
                    del instance.requests[i.request_id]
                elif i.notification_type == NotificationType.NEGATIVE_CONFIRM:
                    # TODO: notify the user, note: an alert will always be received before
                    #  NEGATIVE_CONFIRM
                    del instance.requests[i.request_id]
            elif isinstance(i, AsyncNotification):
                if i.notification_type == AsyncNotificationType.ALERT:
                    pass  # TODO: notify user
            elif isinstance(i, TransferNotification):
                if i.notification_type == NotificationType.ACCEPT:
                    pass
                elif i.notification_type == NotificationType.REJECT:
                    pass
                elif i.notification_type == NotificationType.POSITIVE_CONFIRM:
                    pass
                elif i.notification_type == NotificationType.NEGATIVE_CONFIRM:
                    pass


    def create_farm_service(self, vcid: EdlVcid) -> SimpleQueue[TransferFrame]:
        logger.info(f"Creating FARM-1 Service for VCID {vcid}")
        q: SimpleQueue[TransferFrame] = SimpleQueue()
        self._farms[vcid] = (Farm1(w=20, vcf_count_length=1), q)
        return q

    def get_service(self, vcid: EdlVcid) -> Optional[CopService]:
        entry = self._farms.get(vcid)
        if entry is not None:
            return entry[0]
        else:
            return entry
