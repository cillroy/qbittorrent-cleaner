"""Unit tests for dashboard local-drive helpers."""
import ctypes
import unittest
from unittest.mock import Mock, patch

from drivesutil import format_bytes, get_local_drives


class FormatBytesTests(unittest.TestCase):
    def test_bytes_and_scale(self):
        self.assertEqual(format_bytes(0), "0 B")
        self.assertEqual(format_bytes(512), "512 B")
        self.assertEqual(format_bytes(1024), "1.0 KB")
        self.assertEqual(format_bytes(1024 ** 3), "1.0 GB")
        self.assertEqual(format_bytes(1536 * (1024 ** 3)), "1.5 TB")

    def test_invalid_and_negative(self):
        self.assertEqual(format_bytes(None), "0.0 B")
        self.assertEqual(format_bytes(-10), "0 B")


class LocalDrivesTests(unittest.TestCase):
    def test_fixed_drive_shape_and_percent(self):
        total = 1000
        free = 250

        def drive_type(root):
            return 3 if str(root).upper().startswith("C:") else 2

        def free_space(root, free_ptr, total_ptr, total_free_ptr):
            free_ptr._obj.value = free
            total_ptr._obj.value = total
            total_free_ptr._obj.value = free
            return 1

        def volume_info(root, name_buf, *_args):
            name_buf.value = "OS"
            return 1

        kernel32 = Mock()
        kernel32.GetDriveTypeW.side_effect = drive_type
        kernel32.GetDiskFreeSpaceExW.side_effect = free_space
        kernel32.GetVolumeInformationW.side_effect = volume_info
        fake_windll = Mock()
        fake_windll.kernel32 = kernel32

        with patch("drivesutil.ctypes.windll", fake_windll):
            drives = get_local_drives()

        self.assertEqual(len(drives), 1)
        drive = drives[0]
        self.assertEqual(drive["letter"], "C:")
        self.assertEqual(drive["label"], "OS")
        self.assertEqual(drive["total_bytes"], total)
        self.assertEqual(drive["free_bytes"], free)
        self.assertEqual(drive["used_bytes"], 750)
        self.assertEqual(drive["percent_used"], 75.0)
        self.assertTrue(drive["total_human"])
        self.assertTrue(drive["free_human"])
        self.assertTrue(drive["used_human"])

    def test_zero_total_guard(self):
        def drive_type(root):
            return 3 if str(root).upper().startswith("D:") else 0

        def free_space(root, free_ptr, total_ptr, total_free_ptr):
            free_ptr._obj.value = 0
            total_ptr._obj.value = 0
            total_free_ptr._obj.value = 0
            return 1

        def volume_info(root, name_buf, *_args):
            name_buf.value = ""
            return 1

        kernel32 = Mock()
        kernel32.GetDriveTypeW.side_effect = drive_type
        kernel32.GetDiskFreeSpaceExW.side_effect = free_space
        kernel32.GetVolumeInformationW.side_effect = volume_info
        fake_windll = Mock()
        fake_windll.kernel32 = kernel32

        with patch("drivesutil.ctypes.windll", fake_windll):
            drives = get_local_drives()

        self.assertEqual(len(drives), 1)
        self.assertEqual(drives[0]["percent_used"], 0.0)
        self.assertEqual(drives[0]["letter"], "D:")


if __name__ == "__main__":
    unittest.main()
