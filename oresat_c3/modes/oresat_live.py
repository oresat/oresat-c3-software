"""OreSat Live mode."""

from ._mode import AdcsMode, AdcsPointAxis, Mode


class OreSatLiveMode(Mode):
    """OreSat Live mode."""

    ADCS_MODE = AdcsMode.POINT
    ADCS_AXIS = AdcsPointAxis.NEG_Z

    def __init__(self):
        super().__init__(["dxwifi"])
