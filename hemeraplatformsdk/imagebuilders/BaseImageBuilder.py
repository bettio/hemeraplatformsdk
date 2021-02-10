#!/usr/bin/python3

import bz2
import errno
import gzip
import hashlib
import json
import lzma
import math
import os
import shutil
import subprocess
import tarfile
import zipfile

BLOCKSIZE = 65536
SDK_BUILD_SCRIPT="/usr/bin/build-hemera-image-sdk.sh"
BUILDROOT_DIR="${INITIAL_DIR}"
MYROOT_DIR="${BUILDROOT_DIR}/${IMAGE_NAME}"
MIC_CACHE_DIR="/var/lib/mic-cache"
DEFAULT_COMPRESSION_FORMAT="bz2"
DEFAULT_REPOSITORY_HOST="http://DEFAULT_REPOSITORY_HOST_HERE:82/"


class BaseImageBuilder:
    def __init__(self, image_dictionary, crypto_dictionary, variant=None, version=None):
        self.version = version
        self.variant = variant
        self.data = image_dictionary
        self.crypto = crypto_dictionary
        self.compress = self.data["compress"] if "compress" in self.data else False

        self.internal_post_scripts = []
        self.internal_post_nochroot_scripts = []

        self.built_packages = []

        self.base_image_name = self.data["name"]
        self.image_name = self.data["name"]

        if variant:
            self.image_name += "_"+variant
        if version:
            self.image_name += "-"+version

        self.build_dir = os.path.join(os.getcwd(), "build-"+self.image_name)
        self.output_dir = os.path.join(self.build_dir, self.image_name)

        self.ks_unpack_files_in_image = {}
        self.ks_copy_files_in_image = {}

        try:
            os.makedirs(self.build_dir)
        except OSError as exc:
            if exc.errno == errno.EEXIST and os.path.isdir(self.build_dir):
                pass
            else:
                raise

    def get_image_build_path(self):
        return self.build_dir

    def get_image_name(self):
        return self.image_name

    def get_image_version(self):
        return self.version

    def get_image_variant(self):
        return self.variant

    def build_image(self):
        raise NotImplementedError

    def get_partitions(self):
        raise NotImplementedError

    def prepare_environment(self):
        self.prepare_ks()

    def generate_image_metadata(self, payload):
        if payload:
            hasher = hashlib.sha256()
            with open(payload, 'rb') as afile:
                buf = afile.read(BLOCKSIZE)
                while len(buf) > 0:
                    hasher.update(buf)
                    buf = afile.read(BLOCKSIZE)
            checksum = hasher.hexdigest()
        else:
            checksum = ""

        metadata = {
            'packages': [],
            'appliance_name': self.base_image_name + "_" + self.variant if self.variant else self.base_image_name,
            'version': self.version if self.version else 'rolling',
            'download_size': os.path.getsize(payload) if payload else 0,
            'checksum': checksum
        }

        # Let's read packages
        with open(os.path.join(self.output_dir, self.image_name + ".packages"), "r") as packages:
            for package in [line.rstrip('\n') for line in packages]:
                entries = package.split(" ")
                index = entries[0].rfind(".")
                metadata['packages'].append(entries[0][:index] + "-" + entries[1].split(":")[-1] + entries[0][index:])

        return metadata

    def generate_recovery_metadata(self, payload):
        if payload:
            hasher = hashlib.sha1()
            with open(payload, 'rb') as afile:
                buf = afile.read(BLOCKSIZE)
                while len(buf) > 0:
                    hasher.update(buf)
                    buf = afile.read(BLOCKSIZE)
            checksum = hasher.hexdigest()
        else:
            checksum = ""

        image_name_recovery = self.base_image_name[:-10] if "_installer" in self.base_image_name else self.base_image_name

        metadata = {
            'artifact_type': "recovery",
            'appliance_name': image_name_recovery + "_" + self.variant if self.variant else image_name_recovery,
            'version': self.version,
            'download_size': os.path.getsize(payload) if payload else 0,
            'checksum': checksum
        }

        return metadata

    def __generate_partition_installer_data(self, device):
        return {k: v for k, v in {
                'target': device.data["install_device"],
                'start_sector': device.data["start_sector"] if "start_sector" in device.data else None,
                'end_sector': device.data["end_sector"] if "end_sector" in device.data else None,
                'size': device.data["size"] if "size" in device.data else None,
                'partition_type': device.data["partition_type"] if "partition_type" in device.data else None,
                'name': device.data["name"] if "name" in device.data else None,
                'filesystem_label': device.data["label"] if "label" in device.data else None,
                'flags': device.data["flags"] if "flags" in device.data else None
            }.items() if v is not None}

    def prepare_installer_data(self, built_packages):
        print("-- Generating Installer data...")
        # We need to prepare the installer metadata.
        installer_data = {
            "actions": [],
            "appliance_name": self.base_image_name[:-10] + "_" + self.variant if self.variant \
                else self.base_image_name[:-10],
            "appliance_version": self.version if self.version else 'rolling',
            # This will, in case, be overwritten later.
            "has_recovery": False
        }

        # Order correctly our actions. We need to figure out partition tables first, then all the rest
        partition_tables = {}
        primary_partitions = {}
        extended_parts = {}
        gpt_device_nodes = []
        for device in [d for d, f in built_packages if d.data["type"].startswith("partition")]:
            device_node = device.data["install_device"].rsplit('p', 1)[0]
            try:
                # Support up to 99 partitions because it's 1 LOC more
                partition_number = int(device.data["install_device"][-2:])
            except ValueError:
                try:
                    partition_number = int(device.data["install_device"][-1:])
                except ValueError:
                    print("-- Install device {0} is malformatted!".format(device.data["install_device"]))
                    raise

            partition_table_type = "gpt" if "gpt" in device.data["type"] else "msdos"
            if partition_table_type is "gpt" and device_node not in gpt_device_nodes:
                gpt_device_nodes.append(device_node)
            if device_node in partition_tables:
                assert partition_tables[device_node]["type"] == partition_table_type
            else:
                partition_tables[device_node] = {
                    'type': partition_table_type,
                    'partitions': []
                }

            if partition_number >= 5 and partition_table_type is not "gpt":
                # Extended
                if device_node not in extended_parts:
                    extended_parts[device_node] = []
                extended_parts[device_node].append(device)
            else:
                # We don't care about counting primary partitions in a GPT partition table
                if partition_table_type is not "gpt":
                    if device_node not in primary_partitions:
                        primary_partitions[device_node] = 0
                    primary_partitions[device_node] += 1
                partition_tables[device_node]["partitions"].append(self.__generate_partition_installer_data(device))

        # Check consistency
        for device_node, p_p in primary_partitions.items():
            if p_p == 4 and device_node in extended_parts:
                # Uh-oh.
                raise ValueError("You have specified more than 4 primary partitions on device {0}. You should specify a maximum of 3 primary "
                                 "partitions and any number of extended ones in a msdos partition table.".format(device_node))

        # Handle extended partitions
        for device_node, devices in extended_parts.items():
            extended_start_sector = None
            extended_end_sector = None
            extended_size = None
            if "size" in devices[0].data:
                # 5MB padding
                extended_size = 5
                for d in devices:
                    extended_size += d.data["size"]
            elif "start_sector" in devices[0].data: # Not sure this actually works.
                try:
                    sector_size = self.data["sector_size"]
                except KeyError:
                    # Reasonable defaults
                    sector_size = 512
                # 5MB padding
                pad_sectors = math.ceil((5120 * 1024) / sector_size)
                extended_start_sector = devices[0].data["start_sector"]
                extended_end_sector = devices[-1]["end_sector"] + pad_sectors

            # Add our extended partition to the partition table
            partition_tables[device_node]["partitions"].append({k: v for k, v in {
                'target': device_node,
                'start_sector': extended_start_sector if extended_start_sector else None,
                'end_sector': extended_end_sector if extended_end_sector else None,
                'size': extended_size if extended_size else None,
                'partition_type': "msdos_extended"
            }.items() if v is not None})
            # And now, let's throw in the rest.
            for device in devices:
                partition_tables[device_node]["partitions"].append(self.__generate_partition_installer_data(device))

        # Order partition tables and add options
        for device_node in partition_tables:
            installer_data["actions"].append({
                'type': 'partition_table',
                'target': device_node,
                'table_type': partition_tables[device_node]["type"],
                'partitions': partition_tables[device_node]["partitions"],
                'run_on_full_flash': True,
                'run_on_partial_flash': False,
                # Regardless, never run in recovery mode! Wiping ourselves -> not cool.
                'run_in_recovery_mode': False
            })

        for device, filenames in built_packages:
            installer_data["actions"] += device.get_installer_actions()
            if filenames:
                for f in filenames:
                    self.ks_copy_files_in_image[f] = "/installer/"

        # Fixup copy_recovery action, if any
        for idx, action in enumerate(installer_data["actions"]):
            if action['type'] != 'copy_recovery':
                continue
            # Nice. We have a recovery partition. Let's add this information to our metadata.
            installer_data["has_recovery"] = True
            installer_data["recovery_device"] = action["target"]
            try:
                installer_data["recovery_device_filesystem_label"] = action["filesystem_label"]
            except KeyError:
                pass

            action['files'] = []
            # Do not try! If there's no boot_files but a recovery has been requested, shit is fucked up!
            # Actually, do. If USB boot is not possible, there's not a strict need to have files besides the image.
            try:
                for file in self.data["boot_files"]:
                    try:
                        action["files"].append(file.split(':')[-1])
                    except IndexError:
                        action["files"].append(file)
            except KeyError:
                pass
            action["files"].append("hemeraos.img")
            installer_data["actions"][idx] = action

        # We also set up the cache erase action. This should happen whenever we DON'T wipe /var.
        # So, let's run around our partitions and figure out exactly what holds /var and its subdirectories.
        #
        # Once we get there, we need to wipe out two things: /var/cache, because fuck caching, and most of all
        # /var/lib/rpm. Why? It's pretty obvious: we're installing a whole new set of packages we know nothing about.
        # As such, the RPM DB will get out of sync and this is not bad, this is TERRIBLE.
        #
        # So we wipe /var/lib/rpm, because no RPM DB >>>> out of date RPM DB.
        # On the other hand, our ks/tmpfiles/gravity installation will take care of placing the newly installed
        # RPM DB into /usr/local/lib/rpm, which will be restored by systemd upon first boot. So wiping /var/lib/rpm
        # becomes perfectly safe.
        #
        # tl;dr: wipe these directories regardless, or regret updating.
        partitions = [p for d, filename in built_packages if d.can_be_mounted() or d.can_be_packaged()
                      for p in d.get_partitions()]

        # /var/cache submounts (might happen)
        var_cache_candidates = [p for p in partitions if p["mountpoint"].startswith("/var/cache/")]
        if var_cache_candidates:
            for c in var_cache_candidates:
                if "ubi" in c["install_device"]:
                    installer_data["actions"].append({k: v for k, v in {
                        'type': 'ubi_attach',
                        'target': c["mapped_ubi_node"],
                        'parent_device': c["parent_device"],
                        'run_on_full_flash': False,
                        'run_on_partial_flash': True
                    }.items() if v is not None})
                installer_data["actions"].append({k: v for k, v in {
                    'type': 'erase_directory',
                    'target': c["install_device"],
                    'filesystem_label': c["label"] if "label" in c else None,
                    'relative_path': '',
                    'run_on_full_flash': False,
                    'run_on_partial_flash': True
                }.items() if v is not None})
                if "ubi" in c["install_device"]:
                    installer_data["actions"].append({k: v for k, v in {
                        'type': 'ubi_detach',
                        'target': c["mapped_ubi_node"],
                        'parent_device': c["parent_device"],
                        'run_on_full_flash': False,
                        'run_on_partial_flash': True
                    }.items() if v is not None})

        # /var/cache itself
        try:
            var_cache_partition = [p for p in partitions if p["mountpoint"] == "/var/cache"][0]
            var_cache_relative = ''
        except IndexError:
            try:
                var_cache_partition = [p for p in partitions if p["mountpoint"] == "/var"][0]
                var_cache_relative = 'cache'
            except IndexError:
                var_cache_partition = [p for p in partitions if p["mountpoint"] == "/"][0]
                var_cache_relative = 'var/cache'
        if "ubi" in var_cache_partition["install_device"]:
            installer_data["actions"].append({k: v for k, v in {
                'type': 'ubi_attach',
                'target': var_cache_partition["mapped_ubi_node"],
                'parent_device': var_cache_partition["parent_device"],
                'run_on_full_flash': False,
                'run_on_partial_flash': True
            }.items() if v is not None})
        installer_data["actions"].append({k: v for k, v in {
            'type': 'erase_directory',
            'target': var_cache_partition["install_device"],
            'filesystem_label': var_cache_partition["label"] if "label" in var_cache_partition else None,
            'relative_path': var_cache_relative,
            'run_on_full_flash': False,
            'run_on_partial_flash': True
        }.items() if v is not None})
        if "ubi" in var_cache_partition["install_device"]:
            installer_data["actions"].append({k: v for k, v in {
                'type': 'ubi_detach',
                'target': var_cache_partition["mapped_ubi_node"],
                'parent_device': var_cache_partition["parent_device"],
                'run_on_full_flash': False,
                'run_on_partial_flash': True
            }.items() if v is not None})

        # /var/lib/rpm
        try:
            var_lib_rpm_partition = [p for p in partitions if p["mountpoint"] == "/var/lib/rpm"][0]
            var_lib_rpm_relative = ''
        except IndexError:
            try:
                var_lib_rpm_partition = [p for p in partitions if p["mountpoint"] == "/var/lib"][0]
                var_lib_rpm_relative = 'rpm'
            except IndexError:
                try:
                    var_lib_rpm_partition = [p for p in partitions if p["mountpoint"] == "/var"][0]
                    var_lib_rpm_relative = 'lib/rpm'
                except IndexError:
                    var_lib_rpm_partition = [p for p in partitions if p["mountpoint"] == "/"][0]
                    var_lib_rpm_relative = 'var/lib/rpm'
        if "ubi" in var_lib_rpm_partition["install_device"]:
            installer_data["actions"].append({k: v for k, v in {
                'type': 'ubi_attach',
                'target': var_lib_rpm_partition["mapped_ubi_node"],
                'parent_device': var_lib_rpm_partition["parent_device"],
                'run_on_full_flash': False,
                'run_on_partial_flash': True
            }.items() if v is not None})
        installer_data["actions"].append({k: v for k, v in {
            'type': 'erase_directory',
            'target': var_lib_rpm_partition["install_device"],
            'filesystem_label': var_lib_rpm_partition["label"] if "label" in var_lib_rpm_partition else None,
            'relative_path': var_lib_rpm_relative,
            'run_on_full_flash': False,
            'run_on_partial_flash': True
        }.items() if v is not None})
        if "ubi" in var_lib_rpm_partition["install_device"]:
            installer_data["actions"].append({k: v for k, v in {
                'type': 'ubi_detach',
                'target': var_lib_rpm_partition["mapped_ubi_node"],
                'parent_device': var_lib_rpm_partition["parent_device"],
                'run_on_full_flash': False,
                'run_on_partial_flash': True
            }.items() if v is not None})

        # Orbit's .cache (/var/lib/hemera/orbits/.cache)
        try:
            var_lib_hemera_orbits_partition = [p for p in partitions if p["mountpoint"] == "/var/lib/hemera/orbits"][0]
            var_lib_hemera_orbits_relative = '*/.cache'
        except IndexError:
            try:
                var_lib_hemera_orbits_partition = [p for p in partitions if p["mountpoint"] == "/var/lib/hemera"][0]
                var_lib_hemera_orbits_relative = 'orbits/*/.cache'
            except IndexError:
                try:
                    var_lib_hemera_orbits_partition = [p for p in partitions if p["mountpoint"] == "/var/lib"][0]
                    var_lib_hemera_orbits_relative = 'hemera/orbits/*/.cache'
                except IndexError:
                    try:
                        var_lib_hemera_orbits_partition = [p for p in partitions if p["mountpoint"] == "/var"][0]
                        var_lib_hemera_orbits_relative = 'lib/hemera/orbits/*/.cache'
                    except IndexError:
                        var_lib_hemera_orbits_partition = [p for p in partitions if p["mountpoint"] == "/"][0]
                        var_lib_hemera_orbits_relative = 'var/lib/hemera/orbits/*/.cache'
        if "ubi" in var_lib_hemera_orbits_partition["install_device"]:
            installer_data["actions"].append({k: v for k, v in {
                'type': 'ubi_attach',
                'target': var_lib_hemera_orbits_partition["mapped_ubi_node"],
                'parent_device': var_lib_hemera_orbits_partition["parent_device"],
                'run_on_full_flash': False,
                'run_on_partial_flash': True
            }.items() if v is not None})
        installer_data["actions"].append({k: v for k, v in {
            'type': 'erase_directory',
            'target': var_lib_hemera_orbits_partition["install_device"],
            'filesystem_label': var_lib_hemera_orbits_partition[
                "label"] if "label" in var_lib_rpm_partition else None,
            'relative_path': var_lib_hemera_orbits_relative,
            'run_on_full_flash': False,
            'run_on_partial_flash': True
        }.items() if v is not None})
        if "ubi" in var_lib_hemera_orbits_partition["install_device"]:
            installer_data["actions"].append({k: v for k, v in {
                'type': 'ubi_detach',
                'target': var_lib_hemera_orbits_partition["mapped_ubi_node"],
                'parent_device': var_lib_hemera_orbits_partition["parent_device"],
                'run_on_full_flash': False,
                'run_on_partial_flash': True
            }.items() if v is not None})

        # Additional actions!
        try:
            for action in self.data["additional_actions"]:
                if action["type"] == "flash_kobs_u-boot":
                    installer_data["actions"].append({
                        'type': 'backup_u-boot_environment',
                        'run_on_full_flash': True,
                        'run_on_partial_flash': True
                    })

                    try:
                        installer_data["actions"].append({k: v for k, v in {
                            'type': 'flash_kobs',
                            'target': action["spl_device"],
                            'source': action["spl_file"],
                            'search_exponent': action["search_exponent"] if "search_exponent" in action else 2,
                            'run_on_full_flash': True,
                            'run_on_partial_flash': True
                        }.items() if v is not None})
                        installer_data["actions"].append({k: v for k, v in {
                            'type': 'nandwrite',
                            'target': action["u-boot_device"],
                            'source': action["u-boot_file"],
                            'start': action["u-boot_start"] if "u-boot_start" in action else None,
                            'logical_eraseblock_size': action["logical_eraseblock_size"]
                                                       if "logical_eraseblock_size" in action else None,
                            'run_on_full_flash': True,
                            'run_on_partial_flash': True
                        }.items() if v is not None})
                    except KeyError:
                        # If that's the case, spl_device is not there. So we need to flash_kobs the u-boot file only.
                        installer_data["actions"].append({k: v for k, v in {
                            'type': 'flash_kobs',
                            'target': action["u-boot_device"],
                            'source': action["u-boot_file"],
                            'search_exponent': action["search_exponent"] if "search_exponent" in action else 2,
                            'run_on_full_flash': True,
                            'run_on_partial_flash': True
                        }.items() if v is not None})
                    try:
                        installer_data["actions"].append({k: v for k, v in {
                            'type': 'nandwrite',
                            'target': action["dtb_device"],
                            'source': action["dtb_file"],
                            'start': action["dtb_start"] if "dtb_start" in action else None,
                            'logical_eraseblock_size': action["logical_eraseblock_size"]
                                                       if "logical_eraseblock_size" in action else None,
                            'run_on_full_flash': True,
                            'run_on_partial_flash': True
                        }.items() if v is not None})
                    except KeyError:
                        # Maybe there's no dtb.
                        pass

                    installer_data["actions"].append({
                        'type': 'restore_u-boot_environment',
                        'run_on_full_flash': True,
                        'run_on_partial_flash': True
                    })
                elif action["type"] == "set_u-boot_environment":
                    installer_data["actions"].append({
                        'type': 'u-boot_env_update',
                        'environment': action["environment"],
                        'run_on_full_flash': True,
                        'run_on_partial_flash': True
                    })
                else:
                    raise NotImplementedError("Action not defined!", action)
        except KeyError:
            pass

        # Scripts
        if "scripts" in self.data:
            installer_data["scripts"] = []
            for t in self.data["scripts"]:
                installer_data["scripts"].append({
                    'path': t["path"],
                    'message': t["message"]
                })

        print("-- Installer data has been generated. Will do:")
        print(json.dumps(installer_data, sort_keys=True, indent=4))

        with open(os.path.join(self.build_dir, 'sysrestore.json'), "w") as outfile:
            json.dump(installer_data, outfile)

        # Copy the image and sysrestore, of course
        self.ks_copy_files_in_image[os.path.join(self.build_dir, 'sysrestore.json')] = "/boot/sysconfig/"

        # Add internal scripts
        self.internal_post_scripts.append("mkdir /ramdisk")

    def get_partition_mount_options(self, p):
        fs_options = ''
        try:
            fs_options += p["options"]
        except KeyError:
            additional_options = ""
            try:
                if p["filesystem"] == "ext4":
                    additional_options += ",discard"
            except KeyError:
                # There might be no filesystem at all! (UBI)
                pass

            # Check the mountpoint and behave accordingly for defaults
            if p["mountpoint"].startswith('/var') or p["mountpoint"] == '/recovery':
                fs_options += 'defaults,noatime,relatime{}'.format(additional_options)
                try:
                    if p["readonly"]:
                        # This can't be possible. We don't allow /var to be ro.
                        raise Exception("/var, /recovery and its children cannot be read-only!")
                except KeyError:
                    pass
            else:
                try:
                    if p["readonly"]:
                        fs_options += 'ro{}'.format(additional_options)
                    else:
                        fs_options += 'defaults{}'.format(additional_options)
                except KeyError:
                    # Everything is read-only by default, except /var and its children.
                    fs_options += 'ro{}'.format(additional_options)

        return fs_options

    def prepare_ks(self):
        print("-- Generating Kickstart file...")
        replacements = {
            '@APPLIANCE_NAME@': self.base_image_name,
            '@LANG@': self.data["language"],
            '@KEYMAP@': self.data["keymap"],
            '@TIMEZONE@': self.data["timezone"],
            '@ROOT_PASSWORD@': self.data["root_password"],
            '@ARCH@': self.data["arch"]
        }

        if self.variant:
            replacements['@APPLIANCE_VARIANT@'] = self.variant
        else:
            replacements['@APPLIANCE_VARIANT@'] = ""

        if self.version:
            replacements['@APPLIANCE_VERSION@'] = self.version
        else:
            replacements['@APPLIANCE_VERSION@'] = "rolling"
        try:
            replacements['@BOOTLOADER@'] = "bootloader {}".format(self.data["bootloader"])
        except KeyError:
            replacements['@BOOTLOADER@'] = ""

        # Repositories!
        repositories = []
        repo_arch = self.data["arch"]
        if repo_arch == "i686":
            # Due to the way we do things in Hemera
            repo_arch = "i586"

        for r in self.data["repositories"]:
            # Gather data
            try:
                host = r["host"]
            except KeyError:
                host = DEFAULT_REPOSITORY_HOST
            try:
                repo_name = r["repository_name"]
            except KeyError:
                repo_name = "standard-"+repo_arch
            repo_url = host + r["name"].replace(":", ":/") + "/" + repo_name + "/"

            if r["name"].startswith("Hemera"):
                # It's a Hemera repo. Let's create the name by omitting the Hemera:Version part.
                name = "-".join(r["name"].split(':')[2:]).lower()
            else:
                # It's a customer repository. Let's just remove the first one.
                name = "-".join(r["name"].split(':')[1:]).lower()
            try:
                name += "-"+r["repository_name"]
            except KeyError:
                pass

            repo_string = "repo --name={} --baseurl={}".format(name, repo_url)

            try:
                if r["save"]:
                    repo_string += " --save"
            except KeyError:
                pass

            try:
                if r["debug_info"]:
                    repo_string += " --debuginfo"
            except KeyError:
                repo_string += " --debuginfo"

            try:
                repo_string += " --cost={}".format(r["cost"])
            except KeyError:
                pass
            try:
                repo_string += " --priority={}".format(r["priority"])
            except KeyError:
                pass

            repositories.append(repo_string)

        replacements['@REPOSITORIES@'] = "\n".join(repositories)

        # Packages, quite easy.
        replacements['@PACKAGES@'] = "\n".join(self.data["packages"])

        # Partitions (if not GPT)
        try:
            if "gpt" not in self.data["type"]:
                partitions = []
                for p in self.data["partitions"]:
                    fs_options = self.get_partition_mount_options(p)
                    try:
                        part_disk = p["device"]
                    except:
                        part_disk = "hemeraos"
                    try:
                        part_disk = part_disk.split("/")[-1].rsplit("p", 1)[0]
                    except KeyError:
                        pass

                    part_string = 'part {} --size {} --ondisk {} --fstype={} --fsoptions="{}"'\
                        .format(p["mountpoint"], p["size"], part_disk, p["filesystem"], fs_options)
                    try:
                        part_string += " --start "+p["start_sector"]
                    except KeyError:
                        pass
                    try:
                        if p["bootable"]:
                            part_string += " --boot"
                    except KeyError:
                        pass

                    partitions.append(part_string)
                replacements['@PARTITIONS@'] = "\n".join(partitions)
            else:
                replacements['@PARTITIONS@'] = ""
        except KeyError:
            replacements['@PARTITIONS@'] = ""

        # Remounts.
        remount_partitions = []
        for p in self.get_partitions():
            try:
                if not p["readonly"] and p["mountpoint"] != '/' and not p["mountpoint"].startswith('/var') \
                        and p["mountpoint"] != '/recovery':
                    remount_partitions.append(p["mountpoint"])
            except KeyError:
                try:
                    if p["mountpoint"] != '/' and not p["mountpoint"].startswith('/var') \
                            and p["mountpoint"] != '/recovery':
                        remount_partitions.append(p["mountpoint"])
                except KeyError:
                    pass
        replacements['@REMOUNT_LIST@'] = "\n".join(remount_partitions)

        copy_commands = []
        for src, dest in self.ks_unpack_files_in_image.items():
            if os.path.isabs(src):
                src = os.path.join("/parentroot", src[1:])
            else:
                src = os.path.join("../", src)

            dest = '${INSTALL_ROOT}' + dest
            copy_commands.append("mkdir -p " + dest)
            copy_commands.append("tar --numeric-owner -p --directory={} -xf {}".format(dest, src))
        for src, dest in self.ks_copy_files_in_image.items():
            if os.path.isabs(src):
                src = os.path.join("/parentroot", src[1:])
            else:
                src = os.path.join("../", src)
            dest = '${INSTALL_ROOT}' + dest

            copy_commands.append("mkdir -p " + dest)
            copy_commands.append("cp {} {}".format(src, dest))

        replacements['@COPY_COMMANDS@'] = "\n".join(copy_commands)

        if "serial_login" in self.data:
            serial_logins = []
            for sl in self.data["serial_login"]:
                serial_logins.append("echo {} >> /etc/securetty".format(sl.replace("/dev/", "")))
            replacements['@SERIAL_LOGIN@'] = "\n".join(serial_logins)
        else:
            replacements['@SERIAL_LOGIN@'] = ""

        if "custom_post_scripts" in self.data:
            replacements['@CUSTOM_POST_SCRIPTS@'] = "\n".join(self.data["custom_post_scripts"])
        else:
            replacements['@CUSTOM_POST_SCRIPTS@'] = ""
        if "custom_post_nochroot_scripts" in self.data:
            replacements['@CUSTOM_POST_NOCHROOT_SCRIPTS@'] = "\n".join(self.data["custom_post_nochroot_scripts"])
        else:
            replacements['@CUSTOM_POST_NOCHROOT_SCRIPTS@'] = ""

        replacements['@INTERNAL_POST_SCRIPTS@'] = '\n'.join(self.internal_post_scripts)
        replacements['@INTERNAL_POST_NOCHROOT_SCRIPTS@'] = '\n'.join(self.internal_post_nochroot_scripts)

        # Prepare kickstart template
        module_dir = os.path.dirname(os.path.abspath(__file__))
        textfile_path = os.path.join(module_dir, 'kickstart-template.ks')
        with open(textfile_path) as data_file:
            ks_template = data_file.read()

        for src in replacements:
            ks_template = ks_template.replace(src, replacements[src])

        with open(os.path.join(self.build_dir, self.image_name+".ks"), 'w') as outfile:
            outfile.write(ks_template)

    def run_mic(self, additional_args=None):
        self.prepare_environment()

        print("-- Will now launch mic inside Hemera Platform SDK.")
        sdk_call = ["sdk", "-u", "root", "exec", os.path.join("/parentroot", SDK_BUILD_SCRIPT[1:]), self.image_name,
                    self.data["type"], self.data["arch"], MIC_CACHE_DIR,
                    os.path.join("/parentroot", self.build_dir[1:]), self.image_name+".ks"]

        if additional_args:
            sdk_call += additional_args

        subprocess.check_call(sdk_call)

    def compress_image(self):
        raise NotImplementedError

    def get_image_files(self):
        raise NotImplementedError

    def get_recovery_package_files(self):
        raise NotImplementedError

    def should_compress(self):
        return self.compress

    def set_should_compress(self, compress):
        self.compress = compress

    def compress_file(self, file):
        print("--- Compressing {}...".format(file))
        if "compression_format" not in self.data:
            self.data["compression_format"] = DEFAULT_COMPRESSION_FORMAT

        if self.data["compression_format"] == "bz2":
            compressor_open = bz2.open
        if self.data["compression_format"] == "gz":
            compressor_open = gzip.open
        elif self.data["compression_format"] == "xz":
            compressor_open = lzma.open
        elif self.data["compression_format"] == "zip":
            with zipfile.ZipFile(file+".zip", 'w') as my_zip:
                my_zip.write(file)
            return

        with open(file, 'rb') as f_in, compressor_open(file+"."+self.data["compression_format"], 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
        os.remove(file)

    def compress_files(self, files, out_filename, base_dir=None):
        print("--- Compressing to {}...".format(out_filename))
        if "compression_format" not in self.data:
            self.data["compression_format"] = DEFAULT_COMPRESSION_FORMAT

        if self.data["compression_format"] == "zip":
            with zipfile.ZipFile(out_filename, 'w') as my_zip:
                for file in files:
                    try:
                        my_zip.write(file, arcname=file.replace(base_dir, ""))
                    except TypeError:
                        my_zip.write(file)
        else:
            tar_mode = "w:"
            if self.data["compression_format"] is not None:
                tar_mode += self.data["compression_format"]

            with tarfile.open(out_filename, tar_mode) as tar:
                for file in files:
                    try:
                        tar.add(file, arcname=file.replace(base_dir, ""))
                    except TypeError:
                        tar.add(file)

    def generate_recovery_package(self):
        raise NotImplementedError
