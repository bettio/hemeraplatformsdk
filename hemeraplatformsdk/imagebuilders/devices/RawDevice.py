#!/usr/bin/python3

import binascii
import errno
import math
import os
import subprocess
import sys

import parted

from hemeraplatformsdk.imagebuilders.devices.BaseDevice import BaseDevice
from hemeraplatformsdk.imagebuilders.devices.BaseDevice import ExtractedFileTooBigException
from hemeraplatformsdk.imagebuilders.devices.BaseDevice import WrongPartitionTypeException
from hemeraplatformsdk.imagebuilders.devices.PartedHelper import PartedHelper

DD_SECTORS=8192


class RawDevice(BaseDevice):
    def __init__(self, device_dictionary, image_builder):
        super().__init__(device_dictionary, image_builder)
        assert self.data["type"].startswith("raw")

        try:
            self.filename = os.path.join(self.builder.build_dir,
                                         "{}_{}.raw".format(self.builder.image_name, self.data["install_device"]
                                                            .split("/")[-1].rsplit("p", 1)[0]))
        except KeyError:
            try:
                self.filename = os.path.join(self.builder.build_dir,
                                             "{}_{}.raw".format(self.builder.image_name,
                                                                self.data["partitions"][0]["device"]
                                                                .split("/")[-1].rsplit("p", 1)[0]))
            except KeyError:
                self.filename = os.path.join(self.builder.build_dir,
                                             "{}.raw".format(self.builder.image_name))

        # Allocate and setup
        self.parted_helper = PartedHelper(self.filename)

        self.partition_start = {}
        self.mounted_partitions = []

    def can_be_mounted(self):
        return True

    def get_base_mountpoint(self):
        # We have a set of partitions: let's return the most basic one.
        return sorted([p for p in self.data["partitions"] if "mountpoint" in p],
                      key=lambda x: x["mountpoint"][:-1].count('/'))[0]["mountpoint"]

    def can_be_packaged(self):
        return False

    def has_fstab_entries(self):
        return True

    def needs_file_extraction(self):
        return "dd" in self.data or [p for p in self.data["partitions"] if "flash" in p]

    def extract_file(self, base_path):
        # We need to access the device externally
        self.parted_helper.device.beginExternalAccess()

        try:
            dd_call = ["dd", "if=" + os.path.join(base_path, self.data["dd"]["file"][1:]), "of=" + self.filename]
            print("-- Running dd on built image...")

            try:
                file_size = os.path.getsize(os.path.join(base_path, self.data["dd"]["file"][1:]))
                if file_size > self.data["dd"]["max_file_size"]:
                    raise ExtractedFileTooBigException("Extracted file {} is of size {}, which is bigger than {}. "
                                                       "Aborting.".format(self.data["dd"]["file"],
                                                                          file_size, self.data["dd"]["max_file_size"]))
            except KeyError:
                pass

            try:
                dd_call.append("skip=" + str(self.data["dd"]["input_offset"]))
            except KeyError:
                pass
            try:
                dd_call.append("seek=" + str(self.data["dd"]["output_offset"]))
            except KeyError:
                pass
            dd_call.append("conv=notrunc")
            subprocess.check_call(dd_call)

            try:
                keep_in_image = self.data["dd"]["keep_in_image"]
            except KeyError:
                keep_in_image = False
            if not keep_in_image:
                os.remove(os.path.join(base_path, self.data["dd"]["file"][1:]))
        except KeyError:
            pass

        for p in [p for p in self.data["partitions"] if "flash" in p]:
            # Get the filename
            if p["flash"].startswith(':'):
                filename = os.path.join(base_path, p["flash"][1:])
            else:
                filename = p["flash"]

            # Get the partition
            for partition in self.parted_helper.disk.partitions:
                if partition.name != p["name"]:
                    continue

                print("--- Flashing {} onto {} starting from sector {}".format(filename, partition.name,
                                                                               partition.geometry.start))

                size = os.path.getsize(filename)
                start_sector = partition.geometry.start
                num_sectors = partition.geometry.end - partition.geometry.start

                # let's check as much as possible before doing anything harmful...
                assert num_sectors > 0, \
                    "num_partition_sectors is 0, don't know what to do"
                assert size <= num_sectors * self.parted_helper.device.sectorSize, \
                    "File size is %d, too big for partition of size %d" \
                    % (size, num_sectors * self.parted_helper.device.sectorSize)
                assert start_sector >= 0, \
                    "Start sector is %d" % start_sector

                with open(filename, "rb") as f, open(self.filename, "rb+") as o:
                    o.seek(partition.geometry.start * self.parted_helper.device.sectorSize)
                    buf = f.read(DD_SECTORS * self.parted_helper.device.sectorSize)

                    while len(buf) > 0:
                        if len(buf) % self.parted_helper.device.sectorSize != 0:
                            # we might need to write the last few bytes
                            # and align to multiple of SECTOR_SIZE
                            read_sectors = int(math.ceil(len(buf) / self.parted_helper.device.sectorSize))
                            pad = b'00' * (self.parted_helper.device.sectorSize -
                                           (len(buf) % self.parted_helper.device.sectorSize))
                            buf = binascii.unhexlify(binascii.hexlify(buf) + pad)

                        o.write(buf)
                        buf = f.read(DD_SECTORS * self.parted_helper.device.sectorSize)

                break

            try:
                keep_in_image = p["keep_in_image"]
            except KeyError:
                keep_in_image = False
            if not keep_in_image:
                os.remove(filename)

        # End access to Device
        self.parted_helper.device.endExternalAccess()

    def get_installer_actions(self):
        # Just dd the raw file brutally.
        try:
            return [{
                'type': 'dd',
                'source': os.path.join('/installer', self.filename.split('/')[-1]),
                'target': self.data["install_device"],
                'run_on_full_flash': True,
                'run_on_partial_flash': True
            }]
        except KeyError:
            # This device has nothing to do.
            return []

    def create_device(self):
        self.create_disk("msdos")

    def create_disk(self, type):
        # Let's start by computing overall size.
        try:
            disk_size = self.data["size"]
        except KeyError:
            # Add 8 MB of padding.
            disk_size = 8
            for p in self.data["partitions"]:
                disk_size += p["size"]

        self.parted_helper.create_disk(disk_size, type)
        self.create_partitions()

    def create_partitions(self):
        for p in self.data["partitions"]:
            try:
                geometry = parted.Geometry(self.parted_helper.device, start=p["start_sector"], end=p["end_sector"])
                exact_geom = True
            except KeyError:
                try:
                    start = p["start_sector"]
                except KeyError:
                    start = self.parted_helper.get_free_regions(self.parted_helper.device.optimumAlignment)[-1].start + \
                            self.parted_helper.device.minimumAlignment.offset + \
                            self.parted_helper.device.minimumAlignment.grainSize

                end = start + parted.sizeToSectors(int(p["size"]), 'MiB', self.parted_helper.device.sectorSize)
                geometry = parted.Geometry(self.parted_helper.device, start=start, end=end)
                exact_geom = False

            try:
                fs = parted.FileSystem(type=p["filesystem"], geometry=geometry)
            except KeyError:
                fs = None
                # Don't care
                pass

            try:
                if p["partition_type"] == "extended":
                    part_type = parted.PARTITION_EXTENDED
                elif p["partition_type"] == "logical":
                    part_type = parted.PARTITION_LOGICAL
                elif p["partition_type"] == "primary":
                    part_type = parted.PARTITION_NORMAL
                else:
                    raise WrongPartitionTypeException("{} is not a valid partition type."
                                                      "Valid types are: extended, logical, primary.")
            except KeyError:
                part_type = parted.PARTITION_NORMAL

            partition = self.parted_helper.add_partition(geometry=geometry, name=p["name"] if "name" in p else None,
                                                         part_type=part_type, fs=fs, exact_geom=exact_geom)

            try:
                for flag in p["flags"]:
                    if flag == "msftdata":
                        partition.setFlag(16)
                    elif flag == "boot":
                        partition.setFlag(parted.PARTITION_BOOT)
            except KeyError:
                # Don't care
                pass

            self.parted_helper.disk.commit()

            # Add data
            try:
                self.partition_start[p["mountpoint"]] = partition.geometry.start
            except KeyError:
                pass

            # Format the filesystem, if any
            try:
                # Do this print so we can trigger the exception!
                print("--- Now formatting as {}".format(p["filesystem"]))
                mkfs_call = ["mkfs." + self.data["filesystem"]]
                try:
                    if self.data["filesystem"].startswith("ext"):
                        mkfs_call += ["-L", self.data["label"]]
                    elif self.data["filesystem"] == "vfat":
                        mkfs_call += ["-n", self.data["label"]]
                except KeyError:
                    pass
                mkfs_call += ["/dev/loop7"]
                with open(os.devnull, "w") as f:
                    subprocess.check_call(
                        ["losetup", "-o", str(partition.geometry.start * self.parted_helper.device.sectorSize),
                         "--sizelimit", str((partition.geometry.end - partition.geometry.start) *
                                            self.parted_helper.device.sectorSize),
                         "/dev/loop7", self.filename])
                    subprocess.check_call([mkfs_call], stdout=f, stderr=f)
                    subprocess.check_call(["losetup", "-d", "/dev/loop7"])
            except KeyError:
                # Don't care
                pass

    def mount_device(self, base_path):
        # We want to sort mountpoints based on the occurrences of the number of / (except for the first one, of course).
        # / must always be mounted first. Then we do a rundown of each single tree level for each mountpoint, so that
        # we make sure that no device is obfuscated.
        for p in sorted([p for p in self.data["partitions"] if "mountpoint" in p],
                        key=lambda x: x["mountpoint"][:-1].count('/')):
            # Ignore errors when making dirs
            try:
                os.makedirs(os.path.join(base_path, p["mountpoint"][1:]))
            except IOError as exc:
                if exc.errno == errno.EEXIST:
                    pass
                else:
                    print("--- Warning: creation of directory {} failed: {}."
                          .format(os.path.join(base_path, p["mountpoint"][1:]), exc.strerror), file=sys.stderr)

            print("--- Mounting {}".format(p["mountpoint"]))
            subprocess.check_call(
                ["mount", "-o", "loop,offset=" + str(self.partition_start[p["mountpoint"]] *
                                                     self.parted_helper.device.sectorSize),
                 self.filename, os.path.join(base_path, p["mountpoint"][1:])])
            self.mounted_partitions.append(os.path.join(base_path, p["mountpoint"][1:]))

    def unmount_device(self):
        for p in reversed(self.mounted_partitions):
            print("--- Unmounting {}".format(p))
            subprocess.check_call(["umount", p])

    def get_device_files(self):
        return [self.filename]

    def get_fstab_entries(self):
        entries = []
        for p in self.data["partitions"]:
            check_fs = 0
            if p["mountpoint"].startswith("/var"):
                check_fs = 1
            try:
                entries.append('LABEL="{}" {} {} {} 0 {}'.format(p["label"], p["mountpoint"], p["filesystem"],
                                                                 self.builder.get_partition_mount_options(p),
                                                                 check_fs))
            except KeyError:
                entries.append("{} {} {} {} 0 {}".format(p["device"], p["mountpoint"], p["filesystem"],
                                                         self.builder.get_partition_mount_options(p),
                                                         check_fs))
        return entries

    def get_partitions(self):
        return self.data["partitions"]
