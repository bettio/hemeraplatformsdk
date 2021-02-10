#!/usr/bin/python3

import errno
import math
import os
import shutil
import sys
import tarfile

from hemeraplatformsdk.imagebuilders.BaseImageBuilder import BaseImageBuilder

from hemeraplatformsdk.imagebuilders.devices.BlankPartitionDevice import BlankPartitionDevice
from hemeraplatformsdk.imagebuilders.devices.GPTDevice import GPTDevice
from hemeraplatformsdk.imagebuilders.devices.NANDFileDevice import NANDFileDevice
from hemeraplatformsdk.imagebuilders.devices.PartitionDevice import PartitionDevice
from hemeraplatformsdk.imagebuilders.devices.RawDevice import RawDevice
from hemeraplatformsdk.imagebuilders.devices.UBIDevice import UBIDevice

TMP_MOUNT_PATH="/tmp/image/rootfs"


class RawMultipartImageBuilder(BaseImageBuilder):
    def __init__(self, image_dictionary, crypto_dictionary, variant=None, version=None):
        super().__init__(image_dictionary, crypto_dictionary, variant, version)
        assert self.data["type"] == "raw"

        self.is_compressed = False

        self.compression_extension = ""
        if "compression_format" not in self.data:
            self.compression_extension = ".tar.bz2"
        elif self.data["compression_format"] == "zip":
            self.compression_extension = ".zip"
        else:
            self.compression_extension = ".tar." + self.data["compression_format"]

        # Ignore errors when making dirs
        try:
            os.makedirs(TMP_MOUNT_PATH)
        except IOError as exc:
            if exc.errno == errno.EEXIST:
                pass
            else:
                print("--- Warning: creation of directory {} failed: {}.".format(TMP_MOUNT_PATH, exc.strerror),
                      file=sys.stderr)

        self.devices = []
        next_start_sector = -1

        try:
            sector_size = self.data["sector_size"]
        except KeyError:
            # Reasonable defaults
            sector_size = 512
        # 1MB padding
        pad_sectors = math.ceil((1024 * 1024) / sector_size)

        # Load our devices!
        for d in self.data["devices"]:
            if d["type"] == "raw":
                self.devices.append(RawDevice(d, self))
            elif d["type"] == "ubi":
                self.devices.append(UBIDevice(d, self))
            elif d["type"] == "raw-gpt":
                self.devices.append(GPTDevice(d, self))
            elif d["type"].startswith("partition"):
                # Is it blank?
                if "filesystem" not in d:
                    self.devices.append(BlankPartitionDevice(d, self))
                    continue

                # We need to evaluate start sectors!
                if next_start_sector > 0:
                    if "start_sector" not in d:
                        # We need to force a start sector
                        d["start_sector"] = next_start_sector
                        pass
                    # Check the alignment
                    elif d["start_sector"] < next_start_sector:
                        raise Exception("Sector alignment is wrong for {}! You asked for {}, but minimum start is {}."
                                        .format(d, d["start_sector"], next_start_sector))

                self.devices.append(PartitionDevice(d, self))

                if "start_sector" in d:
                    try:
                        next_start_sector = d["end_sector"]
                    except KeyError:
                        next_start_sector = d["start_sector"] + math.ceil((d["size"] * 1024 * 1024) / sector_size)
                        # Align to boundary
                        next_start_sector = (next_start_sector + pad_sectors - (next_start_sector % pad_sectors))

            elif d["type"] == "nand-file":
                self.devices.append(NANDFileDevice(d, self))

    def build_image(self):
        # Change it to fs.
        self.data["type"] = "fs"
        # We just create it as it is.
        self.run_mic()

        # Time to create the devices now.
        for d in self.devices:
            d.create_device()

        # Mount mountable devices
        for d in sorted([d for d in self.devices if d.can_be_mounted()],
                        key=lambda d: d.get_base_mountpoint()[:-1].count('/')):
            d.mount_device(TMP_MOUNT_PATH)

        # Now, let's unpack the filesystem.
        fs_compressed = tarfile.open(os.path.join(self.output_dir, self.image_name + ".tar"))
        fs_compressed.extractall(path=TMP_MOUNT_PATH)

        # Extract files, if any
        for d in [d for d in self.devices if d.needs_file_extraction()]:
            d.extract_file(TMP_MOUNT_PATH)

        # We shall update fstab now.
        # Given fstab is a bad beast, we basically regenerate it.
        os.rename(os.path.join(TMP_MOUNT_PATH, "/etc/fstab"[1:]),
                  os.path.join(TMP_MOUNT_PATH, "/etc/fstab.generated"[1:]))
        with open(os.path.join(TMP_MOUNT_PATH, "/etc/fstab"[1:]), "w") as f:
            # Filesystem entries
            for d in [d for d in self.devices if d.has_fstab_entries()]:
                for entry in d.get_fstab_entries():
                    print(entry, file=f)
            # Write fixed entries next
            print("devpts     /dev/pts  devpts  gid=5,mode=620   0 0", file=f)
            print("tmpfs      /dev/shm  tmpfs   defaults         0 0", file=f)
            print("proc       /proc     proc    defaults         0 0", file=f)
            print("sysfs      /sys      sysfs   defaults         0 0", file=f)

            # Custom fstab entries
            try:
                for entry in self.data["custom_fstab_entries"]:
                    print(entry, file=f)
            except KeyError:
                pass

        # Now it's time to unmount our mountable devices, so that only what should be in packaged devices is left.
        for d in sorted([d for d in self.devices if d.can_be_mounted()],
                        key=lambda d: d.get_base_mountpoint()[:-1].count('/'), reverse=True):
            d.unmount_device()

        # Let's handle our packaged devices now. Order must be reverse as we need to go backwards (most inner goes first)
        for d in sorted([d for d in self.devices if d.can_be_packaged()],
                        key=lambda d: d.get_base_mountpoint()[:-1].count('/'), reverse=True):
            d.package_target_to_device(TMP_MOUNT_PATH)

        # Get built packages
        for d in self.devices:
            self.built_packages.append((d, d.get_device_files()))

    def compress_image(self):
        if len(self.built_packages) > 1:
            self.compress_files([f for f in [d[1] for d in self.built_packages]],
                                out_filename=os.path.join(self.build_dir, self.image_name+self.compression_extension))
        else:
            self.compress_files([f for f in self.built_packages[0][1]])
        self.is_compressed = True

    def get_image_files(self):
        if self.is_compressed:
            if len(self.built_packages) > 1:
                return self.generate_image_metadata(os.path.join(self.build_dir,
                                                                 self.image_name+self.compression_extension)), \
                                                    os.path.join(self.build_dir,
                                                                 self.image_name+self.compression_extension)
            else:
                built_files = [f for f in os.listdir(self.build_dir) if ".raw" in f]
                return self.generate_image_metadata(os.path.join(self.build_dir,built_files[0])), \
                                                    os.path.join(self.build_dir, built_files[0])
        else:
            return self.generate_image_metadata(None), \
                   self.built_packages

    def get_partitions(self):
        # None.
        partitions = []
        for d in self.devices:
            partitions += d.get_partitions()
        return partitions
