#!/usr/bin/python3

import os
from hemeraplatformsdk.imagebuilders.BaseImageBuilder import BaseImageBuilder


class FsImageBuilder(BaseImageBuilder):
    def __init__(self, image_dictionary, crypto_dictionary, variant=None, version=None):
        super().__init__(image_dictionary, crypto_dictionary, variant, version)
        assert self.data["type"] == "fs"

    def build_image(self):
        # We just create it as it is.
        self.run_mic()
        self.built_packages.append((self.data, os.path.join(self.output_dir, self.image_name + ".tar")))

    def compress_image(self):
        # Ask to compress
        self.compress_file(os.path.join(self.output_dir, self.image_name + ".tar"))

    def get_image_files(self):
        built_files = [f for f in os.listdir(self.output_dir) if ".tar" in f]
        if len(built_files) != 1:
            # WTF
            raise Exception("Tarball not found in build directory")

        return self.generate_image_metadata(os.path.join(self.output_dir, built_files[0])), \
               os.path.join(self.output_dir, built_files[0])

    def get_partitions(self):
        # None.
        return []
