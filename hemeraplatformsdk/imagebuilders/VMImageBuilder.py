#!/usr/bin/python3

import os
import paramiko
import scp
import subprocess
import time

from hemeraplatformsdk.imagebuilders.FsImageBuilder import FsImageBuilder
from hemeraplatformsdk.imagebuilders.BaseImageBuilder import BaseImageBuilder


VM_NAME="HemeraSB2InitVM"
VM_HOST="localhost"
VM_PORT=2223
VM_USER="root"
VM_PASS="rootme"
SB2_INIT_SCRIPT="hemera-sb2-init"


class VMImageBuilder(BaseImageBuilder):
    def __init__(self, image_dictionary, crypto_dictionary, variant=None, version=None):
        super().__init__(image_dictionary, crypto_dictionary, variant, version)
        assert self.data["type"] == "vm"
        self.data["arch"] = "i686"
        try:
            self.skip_vm_init = self.data["init"]
        except KeyError:
            # By default, initialise the VM
            self.skip_vm_init = False
        # Defaults
        if "bootloader" not in self.data:
            self.data["bootloader"] = '--timeout=100  --append="vga=0x315 video=vesafb:mtrr,ywrap quiet"'

    def build_image(self):
        # We have to build our toolchains first
        if "embedded_images" in self.data:
            for toolchain in self.data["embedded_images"]:
                # Add defaults
                if "name" not in toolchain:
                    toolchain["name"] = self.data["name"] + "_toolchain_" + toolchain["arch"]
                if "keymap" not in toolchain:
                    toolchain["keymap"] = self.data["keymap"]
                if "language" not in toolchain:
                    toolchain["language"] = self.data["language"]
                if "timezone" not in toolchain:
                    toolchain["timezone"] = self.data["timezone"]
                if "root_password" not in toolchain:
                    toolchain["root_password"] = self.data["root_password"]
                # Build a fs image
                builder = FsImageBuilder(toolchain, self.crypto)
                # HACK, FIXME: we need this to avoid to script local packages
                builder.internal_post_scripts.append("cp /bin/true /usr/bin/strip")
                builder.build_image()
                # Do not compress it, it's pointless.
                _, toolchain_file = builder.get_image_files()
                target_path = "/srv/hemera/targets/Hemera-{}/".format(toolchain["arch"])
                self.ks_unpack_files_in_image[toolchain_file] = target_path
                # Init toolchain
                if not self.skip_vm_init:
                    self.internal_post_scripts.append('ln -s ../{0}@.service '
                                                      '/lib/systemd/system/basic.target.wants/{0}@{1}.service'
                                                      .format("hemera-sb2-init", toolchain['arch']))

        # We have to build a raw image type
        self.data["type"] = "raw"
        # HACK, FIXME: we need this to avoid to script local packages
        self.internal_post_scripts.append("cp /bin/true /usr/bin/strip")
        # We just create it as it is.
        self.run_mic()
        image_vdi = self.image_name+".vdi"
        # Fix filename
        raw_files = [f for f in os.listdir(self.output_dir) if f.endswith(".raw")]
        if len(raw_files) != 1:
            # WTF
            raise Exception("No raw files found in build directory")

        subprocess.check_call(["qemu-img", "convert", "-f", "raw", "-O", "vdi",
                               os.path.join(self.output_dir, raw_files[0]),
                               os.path.join(self.output_dir, image_vdi)])
        os.remove(os.path.join(self.output_dir, raw_files[0]))

    def compress_image(self):
        # Ask to compress
        self.compress_file(os.path.join(self.output_dir, self.image_name+".vdi"))

    def get_image_files(self):
        built_files = [f for f in os.listdir(self.output_dir) if ".vdi" in f]
        if len(built_files) != 1:
            # WTF
            raise Exception("No VDI files found in build directory")

        return self.generate_image_metadata(os.path.join(self.output_dir, built_files[0])), \
               os.path.join(self.output_dir, built_files[0])

    def get_partitions(self):
        # None.
        return []
