"""Implements CacheStore, the merger of OreSatFileCache with a CFDP Filestore"""

import os
import struct
from bisect import insort_left
from pathlib import Path
from typing import BinaryIO, Optional

import fastcrc.crc32
from cfdppy.exceptions import ChecksumNotImplemented, SourceFileDoesNotExist
from cfdppy.filestore import FilestoreResult, VirtualFilestore
from olaf import OreSatFile, OreSatFileCache
from spacepackets.cfdp import NULL_CHECKSUM_U32, ChecksumType


class CacheStore(VirtualFilestore, OreSatFileCache):
    """Extends an OreSatFileCache with the CFDP filestore interface"""

    # Paths are assumed to be given relative to the cache dir. Since there's no subdirectories
    # allowed, it should always be a basename

    def read_data(
        self, file: Path, offset: Optional[int] = None, read_len: Optional[int] = None
    ) -> bytes:
        with self._lock:
            for f in self._data:
                if file.name == f.name:
                    with open(self._dir + f.name, "rb") as rf:
                        rf.seek(offset or 0)
                        return rf.read(read_len)
            raise FileNotFoundError(file)

    def file_size(self, file: Path) -> int:
        return self.stat(file).st_size

    def read_from_opened_file(self, bytes_io: BinaryIO, offset: int, read_len: int) -> bytes:
        with self._lock:
            bytes_io.seek(offset)
            return bytes_io.read(read_len)

    def is_directory(self, path: Path) -> bool:
        # An oresat cache doesn't allow subdirectories
        return False

    def filename_from_full_path(self, path: Path) -> Optional[str]:
        return path.name

    def file_exists(self, path: Path) -> bool:
        with self._lock:
            return any(path.name == f.name for f in self._data)

    def stat(self, file: Path) -> os.stat_result:
        """Implements os.stat() but for a filestore

        I needed to find the size of a file but there's nothing that I can see in the spec that
        would do it. That said it only gives a minimum recommended set of operations, so maybe
        they just expect you to do it yourself?
        """

        with self._lock:
            for f in self._data:
                if file.name == f.name:
                    return Path(self._dir, f.name).stat()
            raise FileNotFoundError(file)

    def truncate_file(self, file: Path) -> None:
        with self._lock:
            for f in self._data:
                if file.name == f.name:
                    with open(self._dir + f.name, "w"):
                        return
            raise FileNotFoundError(file)

    def write_data(self, file: Path, data: bytes, offset: Optional[int] = None) -> None:
        with self._lock:
            for f in self._data:
                if file.name == f.name:
                    with open(self._dir + f.name, "r+b") as wf:
                        if offset is not None:
                            wf.seek(offset)
                        wf.write(data)
                        return
            raise FileNotFoundError(file)

    def create_file(self, file: Path) -> FilestoreResult:
        with self._lock:
            new = Path(self._dir) / file.name
            try:
                osf = OreSatFile(new)
            except ValueError:
                return FilestoreResult.CREATE_NOT_ALLOWED

            # Does the file already exist?
            if any(file.name == f.name for f in self._data):
                return FilestoreResult.CREATE_NOT_ALLOWED

            new.touch()
            insort_left(self._data, osf)
            return FilestoreResult.CREATE_SUCCESS

    def delete_file(self, file: Path) -> FilestoreResult:
        # I would use OreSatFileCache.remove() here but it doesn't tell me if it failed
        with self._lock:
            for f in self._data:
                if f.name == file.name:
                    os.remove(self._dir + f.name)
                    self._data.remove(f)
                    return FilestoreResult.DELETE_SUCCESS
            return FilestoreResult.DELETE_FILE_DOES_NOT_EXIST

    def rename_file(self, old_file: Path, new_file: Path) -> FilestoreResult:
        # old_file must exist in the cache but new_file can be any valid name
        with self._lock:
            for f in self._data:
                if old_file.name == f.name:
                    try:
                        new = OreSatFile(new_file.name)
                    except ValueError:
                        return FilestoreResult.RENAME_NOT_PERFORMED
                    self._data.remove(f)
                    Path(self._dir, f.name).rename(self._dir + new.name)
                    insort_left(self._data, new)
                    return FilestoreResult.RENAME_SUCCESS
            return FilestoreResult.RENAME_OLD_FILE_DOES_NOT_EXIST

    def replace_file(self, replaced_file: Path, source_file: Path) -> FilestoreResult:
        # both arguments must exist in the cache. replaced keeps its name but get's sources
        # contents. source is removed.
        with self._lock:
            if not any(replaced_file.name == f.name for f in self._data):
                return FilestoreResult.REPLACE_FILE_NAME_ONE_TO_BE_REPLACED_DOES_NOT_EXIST

            for f in self._data:
                if source_file.name == f.name:
                    self._data.remove(f)
                    Path(self._dir, source_file).replace(self._dir + replaced_file.name)
                    return FilestoreResult.REPLACE_SUCCESS
            return FilestoreResult.REPLACE_FILE_NAME_TWO_REPLACE_SOURCE_NOT_EXIST

    def create_directory(self, _dir_name: Path) -> FilestoreResult:
        # OreSatCache doesn't have subdirectoriess
        return FilestoreResult.NOT_PERFORMED

    def remove_directory(self, _dir_name: Path, recursive: bool) -> FilestoreResult:
        # OreSatCache doesn't have subdirectoriess
        return FilestoreResult.NOT_PERFORMED

    def list_directory(
        self, _dir_name: Path, file_name: Path, recursive: bool = False
    ) -> FilestoreResult:
        # dir_name is ignored, there are no directories to be considered
        try:
            listing = OreSatFile(file_name.name)
        except ValueError:
            return FilestoreResult.NOT_PERFORMED

        with self._lock, open(self._dir + file_name.name, "w") as f:
            insort_left(self._data, listing)
            # Explicitly not reading from self._data here to help report invalid states
            for line in os.walk(self._dir) if recursive else os.listdir(self._dir):
                f.write(f"{line}\n")
            return FilestoreResult.SUCCESS

    def calc_modular_checksum(self, file_path: Path) -> bytes:
        """Calculates the modular checksum of the file in file_path.

        This was a module level function in cfdp-py, but it accessed the filesystem directly
        instead of going through a filestore. It needs to access the filestore.
        """
        checksum = 0
        offset = 0
        while True:
            data = self.read_data(file_path, offset, 4)
            offset += 4
            if not data:
                break
            checksum += int.from_bytes(data.ljust(4, b"\0"), byteorder="big", signed=False)

        checksum %= 2**32
        return struct.pack("!I", checksum)

    def calculate_checksum(
        self,
        checksum_type: ChecksumType,
        file_path: Path,
        size_to_verify: int,
        segment_len: int = 4096,
    ) -> bytes:
        if checksum_type == ChecksumType.NULL_CHECKSUM:
            return NULL_CHECKSUM_U32
        if not self.file_exists(file_path):
            raise SourceFileDoesNotExist(file_path)
        if checksum_type == ChecksumType.MODULAR:
            return self.calc_modular_checksum(file_path)
        if segment_len == 0:
            raise ValueError("Segment length can not be 0")
        if checksum_type == ChecksumType.CRC_32:
            crc_func = fastcrc.crc32.iso_hdlc
        elif checksum_type == ChecksumType.CRC_32C:
            crc_func = fastcrc.crc32.iscsi
        else:
            raise ChecksumNotImplemented(checksum_type)
        current = crc_func(b"")
        current_offset = 0
        # Calculate the file CRC
        while current_offset < size_to_verify:
            if current_offset + segment_len > size_to_verify:
                read_len = size_to_verify - current_offset
            else:
                read_len = segment_len
            if read_len > 0:
                current = crc_func(self.read_data(file_path, current_offset, read_len), current)
            current_offset += read_len
        return struct.pack("!I", current)
