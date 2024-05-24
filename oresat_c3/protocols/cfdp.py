"""This module contains bugfixes to cfdp-py implementations.

Most or all of these changes should eventually be submitted upstream.
"""

import struct
from pathlib import Path

from cfdppy.exceptions import SourceFileDoesNotExist
from cfdppy.handler.crc import CrcHelper
from cfdppy.handler.source import SourceHandler
from spacepackets.cfdp import NULL_CHECKSUM_U32, ChecksumType
from spacepackets.cfdp.pdu import FileDataPdu
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
            file_size = self.user.vfs.stat(self._put_req.source_file).st_size
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


class VfsCrcHelper(CrcHelper):
    """CrcHelper but modified to only use Filestore operations.

    It previously would attempt to open the paths passed to it directly instead of asking the
    filestore, which failed when using the above PrefixFilestore.
    """

    def calc_modular_checksum(self, file_path: Path) -> bytes:
        """Calculates the modular checksum of the file in file_path.

        This was a module level function in cfdppy but it accessed the filesystem directly
        instead of going through a filestore. It needs to become a CrcHelper method to use the
        provided filestore.
        """
        checksum = 0
        offset = 0
        while True:
            data = self.vfs.read_data(file_path, offset, 4)
            offset += 4
            if not data:
                break
            checksum += int.from_bytes(data.ljust(4, b"\0"), byteorder="big", signed=False)

        checksum %= 2**32
        return struct.pack("!I", checksum)

    def calc_for_file(self, file_path: Path, file_sz: int, segment_len: int = 4096) -> bytes:
        if self.checksum_type == ChecksumType.NULL_CHECKSUM:
            return NULL_CHECKSUM_U32
        if self.checksum_type == ChecksumType.MODULAR:
            return self.calc_modular_checksum(file_path)
        crc_obj = self.generate_crc_calculator()
        if segment_len == 0:
            raise ValueError("Segment length can not be 0")
        if not self.vfs.file_exists(file_path):
            raise SourceFileDoesNotExist(file_path)
        current_offset = 0

        # Calculate the file CRC
        while current_offset < file_sz:
            if current_offset + segment_len > file_sz:
                read_len = file_sz - current_offset
            else:
                read_len = segment_len
            if read_len > 0:
                crc_obj.update(self.vfs.read_data(file_path, current_offset, read_len))
            current_offset += read_len
        return crc_obj.digest()
