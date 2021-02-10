#!/usr/bin/python3

import parted
import subprocess


class PartedHelper:
    def __init__(self, output_file):
        self.output_file = output_file
        self.disk_type = ""

    def add_partition(self, geometry, name=None, part_type=parted.PARTITION_NORMAL, fs=None, exact_geom=False):
        partition = parted.Partition(self.disk, type=part_type, geometry=geometry, fs=fs)
        if exact_geom:
            constraint = parted.Constraint(exactGeom=partition.geometry)
        else:
            constraint = self.device.optimalAlignedConstraint

        if name and self.disk_type == "gpt":
            # PyParted lacks a higher level API for setting partition name... Whatever.
            res = partition.getPedPartition().set_name(name)
            if not res:
                raise Exception()
        elif name:
            res = partition.getPedPartition().set_name(name)
            if not res:
                raise Exception()

        self.disk.addPartition(partition, constraint)

        return partition

    def get_free_regions(self, align):
        """Get a filtered list of free regions, excluding the gaps due to partition alignment"""
        regions = self.disk.getFreeSpaceRegions()
        new_regions = []
        for region in regions:
            if region.length > align.grainSize:
                new_regions.append(region)
        return new_regions

    def create_disk(self, size, type="gpt"):
        # Create file
        print("--- Creating base disk of size {}".format(str(size)))

        self.disk_type = type

        # fallocate is not supported on alpine - let's use truncate
        subprocess.check_call(["truncate", "-s", "{}M".format(size), self.output_file])
        disk_fd = open(self.output_file, 'ab')
        # os.posix_fallocate(disk_fd.fileno(), 0, int(self.config["size"]) * 1024 * 1024)

        self.device = parted.Device(self.output_file)
        self.disk = parted.freshDisk(self.device, type)
        self.disk.commit()
