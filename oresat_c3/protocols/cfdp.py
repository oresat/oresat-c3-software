"""This module contains bugfixes to cfdp-py implementations.

Most or all of these changes should eventually be submitted upstream.
"""

from cfdppy.exceptions import SourceFileDoesNotExist
from cfdppy.handler.dest import CompletionDisposition, DestHandler
from cfdppy.handler.source import SourceHandler
from spacepackets.cfdp import ConditionCode
from spacepackets.cfdp.pdu import EofPdu, FileDataPdu
from spacepackets.cfdp.pdu.file_data import FileDataParams


class VfsSourceHandler(SourceHandler):
    """A SourceHandler but modified to always and only use Filestore operations"""

    def _prepare_file_params(self):
        """Fixes the parent implementation not using vfs operations for file ops

        in particular file_exists() and stat()
        """
        assert self._put_req is not None
        if self._put_req.metadata_only:
            self._params.fp.metadata_only = True
            self._params.fp.no_eof = True
        else:
            assert self._put_req.source_file is not None
            if not self.user.vfs.file_exists(self._put_req.source_file):
                raise SourceFileDoesNotExist(self._put_req.source_file)
            file_size = self.user.vfs.file_size(self._put_req.source_file)
            if file_size == 0:
                self._params.fp.metadata_only = True
            else:
                self._params.fp.file_size = file_size

    def _prepare_file_data_pdu(self, offset: int, read_len: int):
        """Fixes the parent not using vfs operations

        They opened source_file manually and then used read_from_open_file(), but read_data()
        will do all that for you but properly.
        """
        assert self._put_req is not None
        assert self._put_req.source_file is not None
        file_data = self.user.vfs.read_data(self._put_req.source_file, offset, read_len)
        fd_params = FileDataParams(file_data=file_data, offset=offset, segment_metadata=None)
        file_data_pdu = FileDataPdu(pdu_conf=self._params.pdu_conf, params=fd_params)
        self._add_packet_to_be_sent(file_data_pdu)


class FixedDestHandler(DestHandler):
    """Fixes to varius methods to prevent it from stalling the satellite"""

    def _handle_positive_ack_procedures(self):
        """Positive ACK procedures according to chapter 4.7.1 of the CFDP standard.
        Returns False if the FSM should be called again."""
        assert self._params.positive_ack_params.ack_timer is not None
        assert self._params.remote_cfg is not None
        if self._params.positive_ack_params.ack_timer.timed_out():
            if (
                self._params.positive_ack_params.ack_counter + 1
                >= self._params.remote_cfg.positive_ack_timer_expiration_limit
            ):
                self._declare_fault(ConditionCode.POSITIVE_ACK_LIMIT_REACHED)
                # This is a bit of a hack: We want the transfer completion and the corresponding
                # re-send of the Finished PDU to happen in the same FSM cycle. However, the call
                # order in the FSM prevents this from happening, so we just call the state machine
                # again manually.
                if self._params.completion_disposition == CompletionDisposition.CANCELED:
                    return self.state_machine()
            # The parent version of this method didn't have the else. Because otherwise it'd get
            # stuck in an infinite loop we set POSITIVE_ACK_LIMIT_REACHED to ABANDON_... instead of
            # ..._CANCELLATION. ABANDON_... will reset self._params, meaning we cant rely on
            # completion_disposition so it was then spuriously generating the below finished_pdu().
            # Also because ._params was empty it was generating a malformed PDU that would throw
            # an exception on pack().
            else:
                self._params.positive_ack_params.ack_timer.reset()
                self._params.positive_ack_params.ack_counter += 1
                self._prepare_finished_pdu()
        return None

    def _handle_eof_pdu(self, eof_pdu: EofPdu):
        """There's a bug in spacepackets EofPdu.unpack() where condition_code doesn't get >> 4

        It should because condition_code is < 16 and it eventually gets passed to AckPdu, where
        it gets packed, and then pack() fails because it's trying to pack a value 256.

        It would be very difficult to override EofPdu directly because it gets used everywhere and
        we don't have control over where. This is the next best thing, _handle_eof_pdu is where
        the pdu gets used, so we can fix up the value before it spreads.
        """
        eof_pdu.condition_code >>= 4
        return super()._handle_eof_pdu(eof_pdu)

    def _handle_eof_without_previous_metadata(self, eof_pdu: EofPdu):
        """Same issue as _handle_eof_pdu"""
        eof_pdu.condition_code >>= 4
        return super()._handle_eof_without_previous_metadata(eof_pdu)
