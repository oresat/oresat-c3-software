"""Tests CacheStore"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cfdppy.filestore import FilestoreResult

from oresat_c3.protocols.cachestore import CacheStore


class TestCacheStore(unittest.TestCase):
    """Tests CacheStore"""

    def setUp(self):
        self.cachedir = TemporaryDirectory()
        self.cache = CacheStore(self.cachedir.name)
        self.exists = Path("c3_exists_123")
        self.doesnt = Path("c3_doesntexist_124")
        self.invalid = Path("invalid")
        self.directory = Path(".")
        self.assertTrue(self.directory.is_dir())
        self.assertEqual(self.directory.name, "")

        self.assertEqual(self.cache.create_file(self.exists), FilestoreResult.CREATE_SUCCESS)

    def tearDown(self):
        self.cachedir.cleanup()

    def test_read_data(self):
        """Test read_data()"""
        with self.assertRaises(FileNotFoundError):
            self.cache.read_data(self.doesnt)
        with self.assertRaises(FileNotFoundError):
            self.cache.read_data(self.invalid)
        with self.assertRaises(FileNotFoundError):
            self.cache.read_data(self.directory)

        # Nothing's been written
        self.assertEqual(self.cache.read_data(self.exists), b"")
        data = b"This is a test string of bytes \x01\x02\x03"
        with open(self.cache._dir / self.exists, "wb") as f:
            f.write(data)
        self.assertEqual(self.cache.read_data(self.exists), data)
        self.assertEqual(self.cache.read_data(self.exists, offset=10), data[10:])
        self.assertEqual(self.cache.read_data(self.exists, read_len=10), data[:10])
        self.assertEqual(self.cache.read_data(self.exists, offset=10, read_len=10), data[10:20])

    def test_read_from_opened_file(self):
        """Test read_from_opened_file()"""
        data = b"This is a test string of bytes \x01\x02\x03"
        with open(self.cache._dir / self.exists, "wb") as f:
            f.write(data)

        with open(self.cache._dir / self.exists, "rb") as f:
            self.assertEqual(
                self.cache.read_from_opened_file(f, offset=0, read_len=len(data)), data
            )

    def test_is_directory(self):
        """Test is_directory()"""
        self.assertFalse(self.cache.is_directory(self.exists))
        self.assertFalse(self.cache.is_directory(self.doesnt))
        self.assertFalse(self.cache.is_directory(self.invalid))
        # This one technically is a directory, but it doesn't exist in the cache, so false
        self.assertFalse(self.cache.is_directory(self.directory))

    def test_filename_from_full_path(self):
        """Test filename_from_full_path()"""
        self.assertEqual(self.cache.filename_from_full_path(self.exists), self.exists.name)
        self.assertEqual(self.cache.filename_from_full_path(self.directory), "")

    def test_file_exists(self):
        """Test file_exists()"""
        self.assertTrue(self.cache.file_exists(self.exists))
        self.assertFalse(self.cache.file_exists(self.doesnt))
        self.assertFalse(self.cache.file_exists(self.invalid))
        self.assertFalse(self.cache.file_exists(self.directory))

    def test_stat(self):
        """Test stat()"""
        with self.assertRaises(FileNotFoundError):
            self.cache.stat(self.doesnt)
        with self.assertRaises(FileNotFoundError):
            self.cache.stat(self.invalid)
        with self.assertRaises(FileNotFoundError):
            self.cache.stat(self.directory)

        self.assertEqual(self.cache.stat(self.exists).st_size, 0)
        data = b"This is a test string of bytes \x01\x02\x03"
        self.cache.write_data(self.exists, data)
        self.assertEqual(self.cache.stat(self.exists).st_size, len(data))

    def test_truncate_file(self):
        """Test truncate_file()"""
        with self.assertRaises(FileNotFoundError):
            self.cache.truncate_file(self.doesnt)
        with self.assertRaises(FileNotFoundError):
            self.cache.truncate_file(self.invalid)
        with self.assertRaises(FileNotFoundError):
            self.cache.truncate_file(self.directory)

        full_path = self.cache._dir / self.exists
        self.assertEqual(full_path.stat().st_size, 0)
        self.cache.truncate_file(self.exists)
        self.assertEqual(full_path.stat().st_size, 0)

        data = b"This is a test string of bytes \x01\x02\x03"
        with open(full_path, "wb") as f:
            f.write(data)
        self.assertEqual(full_path.stat().st_size, len(data))
        self.cache.truncate_file(self.exists)
        self.assertEqual(full_path.stat().st_size, 0)

    def test_write_data(self):
        """Test write_data()"""
        data = b"This is a test string of bytes \x01\x02\x03"
        with self.assertRaises(FileNotFoundError):
            self.cache.write_data(self.doesnt, data)
        with self.assertRaises(FileNotFoundError):
            self.cache.write_data(self.invalid, data)
        with self.assertRaises(FileNotFoundError):
            self.cache.write_data(self.directory, data)

        full_path = self.cache._dir / self.exists

        self.cache.write_data(self.exists, data)
        with open(full_path, "rb") as f:
            self.assertEqual(f.read(), data)

        # writes don't truncate
        self.cache.write_data(self.exists, b"a")
        with open(full_path, "rb") as f:
            self.assertEqual(f.read(), b"a" + data[1:])

        self.cache.write_data(self.exists, b"a" * len(data), offset=len(data))
        with open(full_path, "rb") as f:
            self.assertEqual(f.read(), b"a" + data[1:] + b"a" * len(data))

    def test_create_file(self):
        """Test create_file()"""
        self.assertEqual(self.cache.create_file(self.exists), FilestoreResult.CREATE_NOT_ALLOWED)
        self.assertEqual(self.cache.create_file(self.doesnt), FilestoreResult.CREATE_SUCCESS)
        self.assertEqual(self.cache.create_file(self.invalid), FilestoreResult.CREATE_NOT_ALLOWED)
        self.assertEqual(self.cache.create_file(self.directory), FilestoreResult.CREATE_NOT_ALLOWED)

        new = Path("c3_newfile_125")
        self.assertEqual(self.cache.create_file(new), FilestoreResult.CREATE_SUCCESS)
        self.assertTrue(self.cache.file_exists(new))
        self.assertTrue(self.cache.file_exists(self.doesnt))
        self.assertTrue((self.cache._dir / new).exists())
        self.assertTrue((self.cache._dir / self.doesnt).exists())

    def test_delete_file(self):
        """Test delete_file()"""
        self.assertEqual(self.cache.delete_file(self.exists), FilestoreResult.DELETE_SUCCESS)
        self.assertEqual(
            self.cache.delete_file(self.doesnt), FilestoreResult.DELETE_FILE_DOES_NOT_EXIST
        )
        self.assertEqual(
            self.cache.delete_file(self.invalid), FilestoreResult.DELETE_FILE_DOES_NOT_EXIST
        )
        self.assertEqual(
            self.cache.delete_file(self.directory), FilestoreResult.DELETE_FILE_DOES_NOT_EXIST
        )

        self.assertFalse(self.cache.file_exists(self.exists))
        self.assertFalse((self.cache._dir / self.exists).exists())

    def test_rename_file(self):
        """Test rename_file()"""
        self.assertEqual(
            self.cache.rename_file(self.doesnt, self.exists),
            FilestoreResult.RENAME_OLD_FILE_DOES_NOT_EXIST,
        )
        self.assertEqual(
            self.cache.rename_file(self.exists, self.invalid), FilestoreResult.RENAME_NOT_PERFORMED
        )
        self.assertEqual(
            self.cache.rename_file(self.exists, self.doesnt), FilestoreResult.RENAME_SUCCESS
        )

        self.assertTrue(self.cache.file_exists(self.doesnt))
        self.assertFalse(self.cache.file_exists(self.exists))

        self.assertTrue((self.cache._dir / self.doesnt).exists())
        self.assertFalse((self.cache._dir / self.exists).exists())

    def test_replace_file(self):
        """Test replace_file()"""
        self.assertEqual(
            self.cache.replace_file(self.doesnt, self.exists),
            FilestoreResult.REPLACE_FILE_NAME_ONE_TO_BE_REPLACED_DOES_NOT_EXIST,
        )
        self.assertEqual(
            self.cache.replace_file(self.exists, self.invalid),
            FilestoreResult.REPLACE_FILE_NAME_TWO_REPLACE_SOURCE_NOT_EXIST,
        )
        self.assertEqual(
            self.cache.replace_file(self.exists, self.doesnt),
            FilestoreResult.REPLACE_FILE_NAME_TWO_REPLACE_SOURCE_NOT_EXIST,
        )

        self.assertEqual(self.cache.create_file(self.doesnt), FilestoreResult.CREATE_SUCCESS)

        self.assertEqual(
            self.cache.replace_file(self.doesnt, self.exists), FilestoreResult.REPLACE_SUCCESS
        )

        self.assertTrue(self.cache.file_exists(self.doesnt))
        self.assertFalse(self.cache.file_exists(self.exists))

        self.assertTrue((self.cache._dir / self.doesnt).exists())
        self.assertFalse((self.cache._dir / self.exists).exists())

    def test_create_directory(self):
        """Test create_directory()"""
        self.assertEqual(
            self.cache.create_directory(Path(self.cache._dir, "test")),
            FilestoreResult.NOT_PERFORMED,
        )

    def test_remove_directory(self):
        """Test remove_directory()"""
        self.assertEqual(
            self.cache.remove_directory(Path(self.cache._dir), recursive=True),
            FilestoreResult.NOT_PERFORMED,
        )
        self.assertEqual(
            self.cache.remove_directory(Path(self.cache._dir), recursive=False),
            FilestoreResult.NOT_PERFORMED,
        )

    def test_list_directory(self):
        """Test list_directory()"""
        self.assertEqual(
            self.cache.list_directory(Path(), self.invalid), FilestoreResult.NOT_PERFORMED
        )

        dirlist_111 = Path(self.cache._dir, "c3_dir_111.txt")
        self.assertEqual(self.cache.list_directory(Path(), dirlist_111), FilestoreResult.SUCCESS)
        self.assertTrue(self.cache.file_exists(dirlist_111))
        with open(dirlist_111) as f:
            self.assertCountEqual(f.read().split(), {self.exists.name, dirlist_111.name})

        self.assertEqual(self.cache.create_file(self.doesnt), FilestoreResult.CREATE_SUCCESS)
        dirlist_222 = Path(self.cache._dir, "c3_dir_222.txt")
        self.assertEqual(self.cache.list_directory(Path(), dirlist_222), FilestoreResult.SUCCESS)
        self.assertTrue(self.cache.file_exists(dirlist_222))
        with open(dirlist_222) as f:
            self.assertCountEqual(
                f.read().split(),
                {self.exists.name, dirlist_111.name, self.doesnt.name, dirlist_222.name},
            )
