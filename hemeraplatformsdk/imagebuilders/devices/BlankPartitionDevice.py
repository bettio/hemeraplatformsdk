#!/usr/bin/python3

import errno
import os
import sys

from hemeraplatformsdk.imagebuilders.devices.BaseDevice import BaseDevice


class BlankPartitionDevice(BaseDevice):
    def __init__(self, device_dictionary, image_builder):
        super().__init__(device_dictionary, image_builder)
        assert self.data["type"].startswith("partition")
        assert "filesystem" not in self.data

    def can_be_mounted(self):
        return False

    def can_be_packaged(self):
        return False

    def has_fstab_entries(self):
        return False

    def create_device(self):
        # Nothing to do
        pass

    def get_device_files(self):
        return []

    def get_partitions(self):
        return []

    def get_installer_actions(self):
        # This device has nothing to do.
        return []
