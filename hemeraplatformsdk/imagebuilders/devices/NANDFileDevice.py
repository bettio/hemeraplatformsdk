#!/usr/bin/python3

import os
import shutil

from hemeraplatformsdk.imagebuilders.devices.BaseDevice import BaseDevice
from hemeraplatformsdk.imagebuilders.devices.BaseDevice import ExtractedFileTooBigException


class NANDFileDevice(BaseDevice):
    def __init__(self, device_dictionary, image_builder):
        super().__init__(device_dictionary, image_builder)
        assert self.data["type"] == "nand-file"

        try:
            self.filename = os.path.join(self.builder.build_dir, self.data["file"].split(":")[1])
        except IndexError:
            self.filename = os.path.join(self.builder.build_dir, self.data["file"].split("/")[-1])

    def can_be_mounted(self):
        return False

    def can_be_packaged(self):
        return False

    def has_fstab_entries(self):
        return False

    def needs_file_extraction(self):
        return True

    def create_device(self):
        pass

    def extract_file(self, base_path):
        try:
            keep_in_image = self.data["keep_in_image"]
        except KeyError:
            keep_in_image = False

        try:
            extract_filename = os.path.join(base_path, self.data["file"].split(":")[0][1:])
        except IndexError:
            extract_filename = os.path.join(base_path, self.data["file"][1:])

        try:
            if os.path.getsize(extract_filename) > self.data["max_file_size"]:
                raise ExtractedFileTooBigException("Extracted file {} is of size {}, which is bigger than {}. "
                                                   "Aborting.".format(extract_filename,
                                                                      os.path.getsize(extract_filename),
                                                                      self.data["max_file_size"]))
        except KeyError:
            pass

        try:
            if keep_in_image:
                shutil.copyfile(extract_filename,
                                os.path.join(self.builder.build_dir, self.data["file"].split(":")[1]))
            else:
                shutil.move(extract_filename,
                            os.path.join(self.builder.build_dir, self.data["file"].split(":")[1]),
                            copy_function=shutil.copyfile)
        except IndexError:
            if keep_in_image:
                shutil.copy2(extract_filename, self.builder.build_dir)
            else:
                shutil.move(extract_filename, self.builder.build_dir)


    def get_device_files(self):
        return [self.filename]

    def get_installer_actions(self):
        # Just dd the raw file brutally.
        try:
            return [{k: v for k, v in {
                'type': 'nandwrite',
                'target': self.data["install_device"],
                'source': os.path.join('/installer', self.filename.split('/')[-1]),
                'start': self.data["start"] if "start" in self.data else None,
                'logical_eraseblock_size': self.data["logical_eraseblock_size"]
                                           if "logical_eraseblock_size" in self.data else None,
                'run_on_full_flash': True,
                'run_on_partial_flash': True
            }.items() if v is not None}]
        except KeyError:
            # This device has nothing to do.
            return []

    def get_partitions(self):
        # None
        return []
