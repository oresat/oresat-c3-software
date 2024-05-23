"""Implements CacheStore, the merger of OreSatFileCache with a CFDP Filestore"""

import os
from bisect import insort_left
from pathlib import Path
from typing import BinaryIO, Optional

from cfdppy.filestore import FilestoreResult, VirtualFilestore
from olaf import OreSatFile, OreSatFileCache


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
