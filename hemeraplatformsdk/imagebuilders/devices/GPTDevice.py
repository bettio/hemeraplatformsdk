#!/usr/bin/python3

import os
import subprocess

from hemeraplatformsdk.imagebuilders.devices.RawDevice import RawDevice


class GPTDevice(RawDevice):
    def __init__(self, device_dictionary, image_builder):
        super().__init__(device_dictionary, image_builder)
        assert self.data["type"] == "raw-gpt"

    def create_device(self):
        self.create_disk("gpt")

    def unmount_device(self):
        # Before we unmount, fix partition types
        self.fix_partitions_uuid_type()
        super().unmount_device()

    def get_fstab_entries(self):
        entries = []
        for p in self.data["partitions"]:
            try:
                if p["mountpoint"] != "/":
                    # Get the partition
                    for partition in self.parted_helper.disk.partitions:
                        if partition.name != p["name"]:
                            continue

                        print("--- Adding {} to fstab".format(p["mountpoint"]))
                        out = subprocess.check_output(["sgdisk", "--info", str(partition.number), self.filename])
                        guid = out.split(b"\n")[1].split(b":")[-1].replace(b" ", b"") \
                            .replace(b"\n", b"").decode("ascii").lower()

                        entries.append("PARTUUID={} {} {} {} 0 0".format(guid, p["mountpoint"],
                                                                         p["filesystem"],
                                                                         self.builder.get_partition_mount_options(p)))
            except KeyError:
                # Don't care
                pass
        return entries

    def fix_partitions_uuid_type(self):
        # We need to access the device externally
        self.parted_helper.device.beginExternalAccess()

        for x in self.data["partitions"]:
            # Do we need to set a custom type on the partition?
            # Get the partition
            for partition in self.parted_helper.disk.partitions:
                if partition.name != x["name"]:
                    continue

                try:
                    # Do this print so we can trigger the exception!
                    print("--- Setting special UUID {} on partition {} number {}".format(x["partition_type"],
                                                                                         partition.name,
                                                                                         partition.number))
                    with open(os.devnull, "w") as f:
                        subprocess.check_call(["sgdisk","-t",str(partition.number)+":"+
                                               x["partition_type"],self.filename], stdout=f)
                except KeyError:
                    # Don't care
                    pass

                break

        # End access to Device
        self.parted_helper.device.endExternalAccess()

    def get_partitions(self):
        return self.data["partitions"]
