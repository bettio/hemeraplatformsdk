#!/usr/bin/python3

import errno
import os
import subprocess
import sys

from hemeraplatformsdk.imagebuilders.devices.BaseDevice import BaseDevice

TMP_MKFS_MOUNT_PATH = "/tmp/image/build"


class PartitionDevice(BaseDevice):
    def __init__(self, device_dictionary, image_builder):
        super().__init__(device_dictionary, image_builder)
        assert self.data["type"].startswith("partition")

        try:
            self.filename = os.path.join(self.builder.build_dir,
                                         "{}.raw".format(self.data["install_device"]
                                                         .split("/")[-1]))
        except KeyError:
            try:
                self.filename = os.path.join(self.builder.build_dir,
                                             "{}.raw".format(self.data["device"]
                                                             .split("/")[-1]))
            except KeyError:
                self.filename = os.path.join(self.builder.build_dir,
                                             "{}.raw".format(self.builder.image_name))

        # Ignore errors when making dirs
        try:
            os.makedirs(TMP_MKFS_MOUNT_PATH)
        except IOError as exc:
            if exc.errno == errno.EEXIST:
                pass
            else:
                print("--- Warning: creation of directory {} failed: {}.".format(TMP_MKFS_MOUNT_PATH, exc.strerror),
                      file=sys.stderr)

    def can_be_mounted(self):
        return True

    def get_base_mountpoint(self):
        return self.data["mountpoint"]

    def can_be_packaged(self):
        return False

    def has_fstab_entries(self):
        return True

    def create_device(self):
        if self.data["type"].endswith("recovery"):
            # Create /recovery
            self.builder.internal_post_scripts.append("mkdir /recovery")
            return
        # Let's start by creating the loop disk
        # fallocate is not supported on alpine - let's use truncate
        subprocess.check_call(["truncate", "-s", "{}M".format(self.data["size"]), self.filename])
        # os.posix_fallocate(disk_fd.fileno(), 0, int(self.config["size"]) * 1024 * 1024)

        # Format the filesystem
        print("--- Now formatting {} as {}".format(self.data["mountpoint"], self.data["filesystem"]))

        mkfs_call = ["mkfs." + self.data["filesystem"], "-m", "1"]
        try:
            if self.data["filesystem"].startswith("ext"):
                mkfs_call += ["-L", self.data["label"]]
            elif self.data["filesystem"] == "vfat":
                mkfs_call += ["-n", self.data["label"]]
        except KeyError:
            pass
        mkfs_call += ["/dev/loop7"]

        with open(os.devnull, "w") as f:
            subprocess.check_call(["losetup",
                                   "/dev/loop7", self.filename])
            subprocess.check_call(mkfs_call, stdout=f, stderr=f)
            subprocess.check_call(["losetup", "-d", "/dev/loop7"])

    def mount_device(self, base_path):
        if self.data["type"].endswith("recovery"):
            # Nothing to do.
            return
        # Ignore errors when making dirs
        try:
            os.makedirs(os.path.join(base_path, self.data["mountpoint"][1:]))
        except IOError as exc:
            if exc.errno == errno.EEXIST:
                pass
            else:
                print("--- Warning: creation of directory {} failed: {}."
                      .format(os.path.join(base_path, self.data["mountpoint"][1:]), exc.strerror), file=sys.stderr)

        subprocess.check_call(["mount", "-o", "loop", self.filename,
                               os.path.join(base_path, self.data["mountpoint"][1:])])
        self.mount_path = os.path.join(base_path, self.data["mountpoint"][1:])

    def unmount_device(self):
        if self.data["type"].endswith("recovery"):
            # Nothing to do.
            return
        subprocess.check_call(["umount", self.mount_path])

    def get_device_files(self):
        if self.data["type"].endswith("recovery"):
            return []
        return [self.filename]

    def get_installer_actions(self):
        # Just dd the raw file brutally.
        try:
            if self.data["type"].endswith("recovery"):
                return [{k: v for k, v in {
                    'type': 'mkfs',
                    'target': self.data["install_device"],
                    'filesystem': self.data["filesystem"],
                    'filesystem_label': self.data["label"] if "label" in self.data else None,
                    'run_on_full_flash': True,
                    'run_on_partial_flash': True,
                    # Running in recovery mode makes no sense.
                    'run_in_recovery_mode': False
                }.items() if v is not None},
                {k: v for k, v in {
                    'type': 'copy_recovery',
                    'target': self.data["install_device"],
                    'filesystem_label': self.data["label"] if "label" in self.data else None,
                    'run_on_full_flash': True,
                    'run_on_partial_flash': True,
                    # Running in recovery mode makes no sense.
                    'run_in_recovery_mode': False
                }.items() if v is not None}]
            else:
                return [{k: v for k, v in {
                    'type': 'dd',
                    'source': os.path.join('/installer', self.filename.split('/')[-1]),
                    'target': self.data["install_device"],
                    'start_sector': self.data["start_sector"] if "start_sector" in self.data else None,
                    'partition_type': self.data["partition_type"] if "partition_type" in self.data else None,
                    'name': self.data["name"] if "name" in self.data else None,
                    'filesystem_label': self.data["label"] if "label" in self.data else None,
                    'flags': self.data["flags"] if "flags" in self.data else None,
                    'run_on_full_flash': True,
                    'run_on_partial_flash': False if self.data["mountpoint"].startswith('/var') else True
                }.items() if v is not None}]
        except KeyError:
            # This device has nothing to do.
            return []

    def get_fstab_entries(self):
        check_fs = 0
        if self.data["mountpoint"].startswith("/var"):
            check_fs = 1

        try:
            partition_reference = 'LABEL="{}"'.format(self.data["label"])
        except KeyError:
            try:
                partition_reference = self.data["install_device"]
            except KeyError:
                partition_reference = self.data["device"]

        if self.data["type"].endswith("recovery"):
            return ["{} {} {} {} 0 {}".format(partition_reference, "/recovery",
                                              self.data["filesystem"],
                                              self.builder.get_partition_mount_options(self.data)+",noauto", check_fs)]
        return ["{} {} {} {} 0 {}".format(partition_reference, self.data["mountpoint"],
                                          self.data["filesystem"],
                                          self.builder.get_partition_mount_options(self.data), check_fs)]

    def get_partitions(self):
        # Ourselves
        return [self.data]
