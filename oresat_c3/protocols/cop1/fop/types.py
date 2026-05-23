from dataclasses import dataclass
from enum import Enum, auto, unique
from typing import Optional

from common.ccsds import Gvcid
from common.fsm import CopState
from common.service import Indication
from spacepackets.uslp import BypassSequenceControlFlag, ProtocolCommandFlag


@unique
class FopState(CopState):
    """The state of FOP-1

    CCSDS 232.1-B-2 § 5.1.2
    """

    ACTIVE = 1
    RETRANSMIT_NO_WAIT = 2
    RETRANSMIT_WITH_WAIT = 3
    INITIALIZING_NO_BC = 4
    INITIALIZING_WITH_BC = 5
    INITIAL = 6


@unique
class Alert(Enum):
    LIMIT = 0
    T1 = 1
    LOCKOUT = 2
    SYNCH = 3
    NNR = 4
    CLCW = 5
    LLIF = 6
    TERM = 7


class TransferNotificationType(Enum):
    ACCEPT = auto()
    REJECT = auto()
    POSITIVE_CONFIRM = auto()
    NEGATIVE_CONFIRM = auto()


class AsyncNotificationType(Enum):
    ALERT = auto()
    SUSPEND = auto()


@dataclass
class DirectiveNotification(Indication):
    request_id: int
    notification_type: NotificationType

@dataclass
class TransferNotification(Indication):
    request_id: int
    notification_type: NotificationType


@dataclass
class AbortRequest(Indication):
    pass


@dataclass
class TransmitRequestForFrame(Indication):
    bypass_flag: BypassSequenceControlFlag
    command_flag: ProtocolCommandFlag
    v_s: int
    tfdf: bytes


@dataclass
class AsyncNotification(Indication):
    notification_type: AsyncNotificationType
    # Qualifier is the Notification Type's parameter
    # Alert has "Reason Code" but Suspend has no params
    notification_qualifier: Optional[Alert]


class ServiceType(Enum):
    AD = auto()
    BD = auto()


@dataclass
class WaitQueueEntry:
    request_id: int
    gvcid: Gvcid
    fdu: bytes
    service_type: ServiceType


@dataclass
class SentQueueEntry:
    request_id: int  # to generate Transfer Notification back to Higher Procedures
    gvcid: Gvcid  # identifies which VC this frame belongs to
    tfdf: bytes  # the master copy for retransmission
    n_s: int  # N(S) sequence number, needed to track NN(R)
    to_be_retransmitted: bool = False  # from section 5.1.5
