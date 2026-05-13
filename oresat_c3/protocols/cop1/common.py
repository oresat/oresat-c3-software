from dataclasses import dataclass
from math import ceil

from spacepackets.uslp import TransferFrame

from ..uslp import Gvcid
from .util import BoundedDeque


@dataclass
class Indication:
    """This is the base for COP indications. Sometimes referred to as requests, directives, signals,
    notifications, or indications depending on the context.

    Parameters
    ----------
    gvcid: Gvcid
        The Global Virtual Channel Identifier for the frame
    """

    gvcid: Gvcid


class ServiceInterface:
    """A generic interface to a COP service.

    For example, in an interface to a lower procedure, the lower procedure would insert a frame into
    the buffer and notify the service by inserting a `ValidFrameArrivedIndication`. The COP service
    can then check the signal buffer for signals, and if signaled to process a new frame, fetch from
    the buffer.

    Attributes
    ----------
    buffer : BoundedDeque[TransferFrame]
        The USLP frame buffer for this interface. For example, in an interface to a lower procedure,
        the lower procedure would insert frames and COP would receive them.
    signal : BoundedDeque[Indication]
        The COP-1 standard interchangeably calls these signals, indications, or notifications
        depending on the context.
    """

    def __init__(self, buffer_size: int, signal_size: int = 0) -> None:
        """

        Parameters
        ----------
        buffer_size
            The size of the frame buffer.
        signal_size
            The size of the signal queue. If <= 0, the signal queue will automatically be sized
            as 1.25x the buffer size, to accommodate both frame indications for a full buffer, and
            leave some room for any additional signals (such as aborted indications).
        """

        self.buffer: BoundedDeque[TransferFrame] = BoundedDeque(buffer_size)
        self.signal: BoundedDeque[Indication] = BoundedDeque(
            signal_size if signal_size > 0 else ceil(buffer_size * 1.25)
        )


class CopService:
    """An abstraction for COP-1 services (FARM and FOP).

    Attributes
    ----------
    lower_interface: ServiceInterface
        The interface from the lower procedures ("inputs"). The COP service is only expected to
        fetch from this interface.
    higher_interface: ServiceInterface
        The interface to the higher procedures ("outputs"). A COP service is only expected to insert
        into this interface.
    """

    def __init__(self, buffer_size: int = 10) -> None:
        """

        Parameters
        ----------
        buffer_size
            The size of the procedure interface buffers. Given a FOP_SLIDING_WINDOW_WIDTH *K*,
            it is recommended to set `buffer_size` >= K. By default, K=10 in YAMCS.
        """
        # from lower procedures
        self.lower_interface: ServiceInterface = ServiceInterface(buffer_size)
        # to higher procedures
        self.higher_interface: ServiceInterface = ServiceInterface(buffer_size)

    def tick(self) -> None:
        raise NotImplemented
