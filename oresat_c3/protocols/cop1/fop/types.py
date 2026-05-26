from dataclasses import dataclass
from enum import Enum, auto, unique
from typing import Optional

from spacepackets.uslp import BypassSequenceControlFlag, ProtocolCommandFlag

from common.ccsds import Gvcid
from common.fsm import CopState
from common.service import Indication


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


class ServiceType(Enum):
    AD = auto()
    BD = auto()


class NotificationType(Enum):
    ACCEPT = auto()
    REJECT = auto()
    POSITIVE_CONFIRM = auto()
    NEGATIVE_CONFIRM = auto()


class AsyncNotificationType(Enum):
    ALERT = auto()
    SUSPEND = auto()


class DirectiveType(Enum):
    INITIATE_AD_NO_CLCW = auto()
    INITIATE_AD_WITH_CLCW = auto()
    INITIATE_AD_WITH_UNLOCK = auto()
    INITIATE_AD_WITH_SET_V_R = auto()
    TERMINATE_AD = auto()
    RESUME_AD = auto()
    SET_V_S = auto()
    SET_SLIDING_WINDOW_WIDTH = auto()
    SET_T1 = auto()
    SET_TRANSMISSION_LIMIT = auto()
    SET_TIMEOUT_TYPE = auto()


@dataclass
class DirectiveNotification(Indication):
    request_id: int
    notification_type: NotificationType


@dataclass
class DirectiveRequest(Indication):
    request_id: int
    directive_type: DirectiveType
    directive_qualifier: int = 0


@dataclass
class RequestToTransferFdu(Indication):
    request_id: int
    fdu: bytes
    service_type: ServiceType


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
