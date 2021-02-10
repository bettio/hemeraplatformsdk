#!/usr/bin/python3

import configparser
import os
import shutil
import subprocess

from hemeraplatformsdk.imagebuilders.devices.BaseDevice import BaseDevice


class UBIDevice(BaseDevice):
    def __init__(self, device_dictionary, image_builder):
        super().__init__(device_dictionary, image_builder)
        assert self.data["type"] == "ubi"

        try:
            self.do_ubinize = self.data["ubinize"]
        except KeyError:
            self.do_ubinize = False

        self.filename = os.path.join(self.builder.build_dir,
                                     "{}.{}".format(self.data["mapped_node"].split("/")[-1],
                                                    "ubi" if self.do_ubinize else "img"))

        # Setup some automated properties for our volumes
        for index, v in enumerate(sorted(self.data["volumes"], key=lambda v: v["mountpoint"][:-1].count('/'), reverse=True)):
            v["install_device"] = "{}_{}".format(self.data["mapped_node"], index)
            v["mapped_ubi_node"] = self.data["mapped_node"]
            v["parent_device"] = self.data["install_device"]

    def can_be_mounted(self):
        return False

    def get_base_mountpoint(self):
        return sorted([v["mountpoint"] for v in self.data["volumes"]], key=lambda v: v[:-1].count('/'))[0]

    def can_be_packaged(self):
        return True

    def create_device(self):
        pass

    def has_fstab_entries(self):
        return True

    def get_installer_actions(self):
        # Just dd the raw file brutally.
        try:
            try:
                do_ubinize = self.data["ubinize"]
            except KeyError:
                do_ubinize = False

            if do_ubinize:
                return [{
                    'type': 'ubiformat',
                    'target': self.data["install_device"],
                    'source': os.path.join('/installer', self.filename.split('/')[-1]),
                    'subpage_size': self.data["subpage_size"] if "subpage_size" in self.data else None,
                    'run_on_full_flash': True,
                    'run_on_partial_flash': True
                }]
            else:
                actions = [{
                    'type': 'ubiformat',
                    'target': self.data["install_device"],
                    'subpage_size': self.data["subpage_size"] if "subpage_size" in self.data else None,
                    'run_on_full_flash': True,
                    'run_on_partial_flash': False
                }]
                actions += [{
                    'type': 'ubiupdatevol',
                    'target': '{}_{}'.format(self.data["mapped_node"], index),
                    'size': v["size"],
                    'source': os.path.join('/installer', os.path.join(self.builder.build_dir, "{}_{}.img"
                                                                      .format(self.data["mapped_node"].split("/")[-1],
                                                                              index)).split('/')[-1]),
                    'name': v["name"] if 'name' in v else v["mountpoint"][1:].replace("/", "_") if v["mountpoint"] != "/" else 'rootfs',
                    'parent_device': self.data["install_device"],
                    'immutable': v["immutable"] if "immutable" in v else False,
                    'run_on_full_flash': True,
                    'run_on_partial_flash': False if v["mountpoint"].startswith('/var') else True
                } for index, v in enumerate(sorted(self.data["volumes"], key=lambda v: v["mountpoint"][:-1].count('/'), reverse=True))]
                return actions
        except KeyError:
            # This device has nothing to do.
            return []

    def package_target_to_device(self, base_path):
        for index, v in enumerate(sorted(self.data["volumes"], key=lambda v: v["mountpoint"][:-1].count('/'), reverse=True)):
            filename = os.path.join(self.builder.build_dir,
                                    "{}_{}.ubi".format(self.data["mapped_node"].split("/")[-1].rsplit("p", 1)[0], index))

            filename_img = os.path.join(self.builder.build_dir,
                                        "{}_{}.img".format(self.data["mapped_node"].split("/")[-1].rsplit("p", 1)[0], index))
            # We need to craft the correct commands for mkfs and ubinize
            subprocess.check_call(["mkfs.ubifs", "-q", "-r", os.path.join(base_path, v["mountpoint"][1:]),
                                   "-o", filename_img, "-e", str(self.data["logical_eraseblock_size"]),
                                   "-c", str(int(((v["size"] + 1) * 1024 * 1024) /
                                                 self.data["logical_eraseblock_size"])),
                                   "-m", str(self.data["minimum_unit_size"])])
            shutil.rmtree(os.path.join(base_path, v["mountpoint"][1:]))
            # Ignore errors when making dirs
            try:
                os.makedirs(os.path.join(base_path, v["mountpoint"][1:]))
            except IOError as exc:
                if exc.errno == errno.EEXIST:
                    pass
                else:
                    print("--- Warning: creation of directory {} failed: {}."
                          .format(os.path.join(base_path, v["mountpoint"][1:]), exc.strerror), file=sys.stderr)

        try:
            do_ubinize = self.data["ubinize"]
        except KeyError:
            do_ubinize = False

        # TODO, FIXME: Support new syntax with ubinize
        if do_ubinize:
            ubiconfig = configparser.ConfigParser()
            ubiconfig["ubifs"] = {
                'mode': 'ubi',
                'image': filename_img,
                'vol_id': 0,
                'vol_size': '{}MiB'.format(self.data["size"]),
                'vol_type': 'dynamic',
                'vol_name': v["name"] if 'name' in self.data else
                            self.data["mountpoint"].replace("/", "_") if self.data["mountpoint"] != "/" else 'rootfs',
                'vol_flags': 'autoresize'
            }

            with open(os.path.join(self.builder.build_dir, 'ubifs.conf'), 'w') as configfile:
                ubiconfig.write(configfile)

            ubinize_args = ["ubinize", "-o", filename, "-p", str(self.data["physical_eraseblock_size"]), "-m",
                            str(self.data["minimum_unit_size"])]
            try:
                ubinize_args += ["-s", str(self.data["subpage_size"])]
            except KeyError:
                pass
            ubinize_args.append(os.path.join(self.builder.build_dir, 'ubifs.conf'))
            subprocess.check_call(ubinize_args)

            os.remove(filename_img)
            os.remove(os.path.join(self.builder.build_dir, 'ubifs.conf'))

    def get_device_files(self):
        if self.do_ubinize:
            return None
        else:
            return [os.path.join(self.builder.build_dir, "{}_{}.img"
                                 .format(self.data["mapped_node"].split("/")[-1], index))
                    for index, v in enumerate(sorted(self.data["volumes"], key=lambda v: v["mountpoint"][:-1].count('/'), reverse=True))]

    def get_fstab_entries(self):
        return ["{}_{} {} {} {} 0 0".format(self.data["mapped_node"], index, v["mountpoint"], "ubifs",
                                            self.builder.get_partition_mount_options(v))
                for index, v in enumerate(sorted(self.data["volumes"], key=lambda v: v["mountpoint"][:-1].count('/'), reverse=True))]

    def get_partitions(self):
        # Get our volumes.
        return self.data["volumes"]
