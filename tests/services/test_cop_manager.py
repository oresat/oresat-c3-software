"""Tests for the COP Manager."""

import unittest
from queue import SimpleQueue

from ccsds_cop.cop_1 import ControlWord
from ccsds_cop.cop_1.fop import (
    Alert,
    AsyncNotification,
    AsyncNotificationType,
    DirectiveNotification,
    NotificationType,
    TransferNotification,
)

from oresat_c3.protocols.edl_packet import EdlVcid
from oresat_c3.services.cop_manager import CopManagerService, FopSupervisorState


def _make_clcw(vcid: int, report_value: int = 0) -> ControlWord:
    return ControlWord(vcid=vcid, report_value=report_value)


class TestFopManagerSupervisor(unittest.TestCase):
    """Test the FOP-1 supervisor state machine in CopManagerService."""

    def setUp(self):
        self.send_queue: SimpleQueue[bytes] = SimpleQueue()
        self.service = CopManagerService()
        self.fdu_queue = self.service.create_fop_service(EdlVcid.C3_COMMAND, self.send_queue)
        self.instance = self.service._fops[EdlVcid.C3_COMMAND]

    def _push_to_higher(self, notification) -> None:
        self.instance.service.interface.to_higher.try_appendleft(notification)

    def _clcw(self, report_value: int = 0) -> ControlWord:
        return _make_clcw(EdlVcid.C3_COMMAND.value, report_value)

    def _directive_notification(self, notification_type: NotificationType) -> DirectiveNotification:
        return DirectiveNotification(
            gvcid=self.instance.gvcid,
            request_id=0,
            notification_type=notification_type,
        )

    def _alert(self, alert: Alert) -> AsyncNotification:
        return AsyncNotification(
            gvcid=self.instance.gvcid,
            notification_type=AsyncNotificationType.ALERT,
            notification_qualifier=alert,
        )

    def _suspend(self) -> AsyncNotification:
        return AsyncNotification(
            gvcid=self.instance.gvcid,
            notification_type=AsyncNotificationType.SUSPEND,
            notification_qualifier=None,
        )

    def test_initiating_on_clcw(self) -> None:
        self.assertEqual(self.instance.state, FopSupervisorState.IDLE)
        self.service.dispatch_clcw(self._clcw())
        self.service._process_clcw()
        self.assertEqual(self.instance.state, FopSupervisorState.INITIATING)

    def test_active_on_positive_confirm(self) -> None:
        self.instance.state = FopSupervisorState.INITIATING
        self._push_to_higher(self._directive_notification(NotificationType.POSITIVE_CONFIRM))
        self.service._process_fop_higher(self.instance)
        self.assertEqual(self.instance.state, FopSupervisorState.ACTIVE)

    def test_initiating_resets_recovery_attempts(self) -> None:
        self.instance.state = FopSupervisorState.INITIATING
        self.instance.recovery_attempts = 2
        self._push_to_higher(self._directive_notification(NotificationType.POSITIVE_CONFIRM))
        self.service._process_fop_higher(self.instance)
        self.assertEqual(self.instance.recovery_attempts, 0)

    def test_suspend_notification(self) -> None:
        self.instance.state = FopSupervisorState.ACTIVE
        self._push_to_higher(self._suspend())
        self.service._process_fop_higher(self.instance)
        self.assertEqual(self.instance.state, FopSupervisorState.SUSPENDED)

    def test_active_to_recovering_on_alert(self) -> None:
        self.instance.state = FopSupervisorState.ACTIVE
        self._push_to_higher(self._alert(Alert.SYNCH))
        self.service._process_fop_higher(self.instance)
        self.assertEqual(self.instance.state, FopSupervisorState.RECOVERING)

    def test_suspend_to_initiating_on_clcw(self) -> None:
        self.instance.state = FopSupervisorState.SUSPENDED
        self.service.dispatch_clcw(self._clcw())
        self.service._process_clcw()
        self.assertEqual(self.instance.state, FopSupervisorState.INITIATING)

    def test_recovering_on_positive_confirm(self) -> None:
        self.instance.state = FopSupervisorState.RECOVERING
        self._push_to_higher(self._directive_notification(NotificationType.POSITIVE_CONFIRM))
        self.service._process_fop_higher(self.instance)
        self.assertEqual(self.instance.state, FopSupervisorState.ACTIVE)

    def test_recovering_to_bd_fallback(self) -> None:
        self.instance.state = FopSupervisorState.ACTIVE
        for _ in range(self.service.MAX_RECOVERY_ATTEMPTS + 1):
            self._push_to_higher(self._alert(Alert.SYNCH))
            self.service._process_fop_higher(self.instance)
        self.assertEqual(self.instance.state, FopSupervisorState.BD_FALLBACK)

    def test_term_alert_goes_to_idle(self) -> None:
        self.instance.state = FopSupervisorState.ACTIVE
        self.instance.recovery_attempts = self.service.MAX_RECOVERY_ATTEMPTS + 5
        self._push_to_higher(self._alert(Alert.TERM))
        self.service._process_fop_higher(self.instance)
        self.assertEqual(self.instance.state, FopSupervisorState.IDLE)

    def test_fdus_not_drained_when_idle(self) -> None:
        self.instance.state = FopSupervisorState.IDLE
        self.fdu_queue.put_nowait(b"data")
        self.service._process_fop_higher(self.instance)
        self.assertFalse(self.fdu_queue.empty())

    def test_fdus_not_drained_when_initiating(self) -> None:
        self.instance.state = FopSupervisorState.INITIATING
        self.fdu_queue.put_nowait(b"data")
        self.service._process_fop_higher(self.instance)
        self.assertFalse(self.fdu_queue.empty())

    def test_fdus_not_drained_when_recovering(self) -> None:
        self.instance.state = FopSupervisorState.RECOVERING
        self.fdu_queue.put_nowait(b"data")
        self.service._process_fop_higher(self.instance)
        self.assertFalse(self.fdu_queue.empty())

    def test_fdus_not_drained_when_suspended(self) -> None:
        self.instance.state = FopSupervisorState.SUSPENDED
        self.fdu_queue.put_nowait(b"data")
        self.service._process_fop_higher(self.instance)
        self.assertFalse(self.fdu_queue.empty())

    def test_transfer_reject_does_not_raise(self) -> None:
        self.instance.state = FopSupervisorState.ACTIVE
        self._push_to_higher(
            TransferNotification(
                gvcid=self.instance.gvcid,
                request_id=1,
                notification_type=NotificationType.REJECT,
            )
        )
        self.service._process_fop_higher(self.instance)

    def test_transfer_negative_confirm_does_not_raise(self) -> None:
        self.instance.state = FopSupervisorState.ACTIVE
        self._push_to_higher(
            TransferNotification(
                gvcid=self.instance.gvcid,
                request_id=1,
                notification_type=NotificationType.NEGATIVE_CONFIRM,
            )
        )
        self.service._process_fop_higher(self.instance)

    def test_unknown_vcid_in_clcw_does_not_raise(self) -> None:
        self.service.dispatch_clcw(_make_clcw(vcid=63))
        self.service._process_clcw()


if __name__ == "__main__":
    unittest.main()
