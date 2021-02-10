#!/usr/bin/python3

import errno
import json
import os
import shutil
import subprocess
from hemeraplatformsdk.imagebuilders.BaseImageBuilder import BaseImageBuilder
from hemeraplatformsdk.UpdatePackageGenerator import generate_squash_package


class SquashImageBuilder(BaseImageBuilder):
    def __init__(self, image_dictionary, crypto_dictionary, variant=None, version=None):
        super().__init__(image_dictionary, crypto_dictionary, variant, version)
        assert self.data["type"] == "squash"
        self.image_filename = "hemeraos.img"
        self.squash_package_dir = os.path.join(self.build_dir, "squash-package")
        self.is_compressed = False

        self.compression_extension = ""
        if "compression_format" not in self.data:
            self.compression_extension = ".tar.bz2"
        elif self.data["compression_format"] == "zip":
            self.compression_extension = ".zip"
        else:
            self.compression_extension = ".tar."+self.data["compression_format"]

        try:
            os.makedirs(self.squash_package_dir)
        except OSError as exc:
            if exc.errno == errno.EEXIST and os.path.isdir(self.squash_package_dir):
                pass
            else:
                raise

    def build_image(self):
        # We create an unpackaged fs (squash) image.
        self.run_mic()

        # We extract our files
        try:
            for f in self.data["boot_files"]:
                try:
                    shutil.copyfile(os.path.join(self.output_dir, self.image_name, "boot", f.split(":")[0]),
                                    os.path.join(self.squash_package_dir, f.split(":")[1]))
                except IndexError:
                    shutil.copy2(os.path.join(self.output_dir, self.image_name, "boot", f), self.squash_package_dir)
        except KeyError:
            # We might not need anything.
            pass

        # We embed basic metadata into the package file.
        with open(os.path.join(self.squash_package_dir, "metadata"), 'w') as outfile:
            json.dump(self.generate_image_metadata(None), outfile)

        # Now, we invoke our mkhemerasquashfs tool
        generate_squash_package(self.crypto, os.path.join(self.output_dir, self.image_name),
                                os.path.join(self.squash_package_dir, self.image_filename), remove_uid_gid=False)

    def compress_image(self):
        # We create a zip file.
        self.compress_files([os.path.join(self.squash_package_dir, f) for f in os.listdir(self.squash_package_dir)],
                            os.path.join(self.build_dir, self.image_name+self.compression_extension),
                            base_dir=self.squash_package_dir)
        # Add to built packages for installer
        self.built_packages.append((self.data, os.path.join(self.build_dir, self.image_name+self.compression_extension)))
        self.is_compressed = True

    def get_image_files(self):
        if self.is_compressed:
            return self.generate_image_metadata(os.path.join(self.build_dir, self.image_name+self.compression_extension)), \
                   os.path.join(self.build_dir, self.image_name+self.compression_extension)
        else:
            return self.generate_image_metadata(None), \
                   [os.path.join(self.output_dir, f) for f in os.listdir(self.squash_package_dir)]

    def get_recovery_package_files(self):
        return self.generate_recovery_metadata(os.path.join(self.build_dir, self.image_name+"_recovery.hpd")) , \
               os.path.join(self.build_dir, self.image_name + "_recovery.hpd")

    def generate_recovery_package(self):
        # Generate our squash package. But add our partial_flash file first.
        with open(os.path.join(self.squash_package_dir, "partial_flash"), 'w+') as partial_flash:
            partial_flash.write('Generated by Hemera Image Builder')
        generate_squash_package(self.data, self.squash_package_dir,
                                os.path.join(self.build_dir, self.image_name+"_recovery.hpd"))
        os.remove(os.path.join(self.squash_package_dir, "partial_flash"))

    def get_partitions(self):
        # None.
        return []
