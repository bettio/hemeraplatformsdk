#!/usr/bin/python3

import argparse
import json
import os
import shutil

import hemeraplatformsdk
from hemeraplatformsdk.ImageConfigurationManager import ImageConfigurationManager
from hemeraplatformsdk.imagebuilders.FsImageBuilder import FsImageBuilder
from hemeraplatformsdk.imagebuilders.SquashImageBuilder import SquashImageBuilder
from hemeraplatformsdk.imagebuilders.VMImageBuilder import VMImageBuilder
from hemeraplatformsdk.imagebuilders.RawMultipartImageBuilder import RawMultipartImageBuilder


class ReleaseInStoreException(Exception):
    def __init__(self,*args,**kwargs):
        Exception.__init__(self,*args,**kwargs)


class ImageBuilder:
    def __init__(self, filename, skip_crypto=False, skip_upload=False):
        self.configuration = ImageConfigurationManager(filename, skip_crypto, skip_upload)

        self.builders = []

        if self.configuration.get_image_version():
            # Check whether one of the storages actually has this version already. If that is the case, abort.
            for u in self.configuration.get_upload_managers():
                try:
                    if u.check_store_has_image(self.configuration.get_image()["name"],
                                               self.configuration.get_image()["group"],
                                               version=self.configuration.get_image_version(),
                                               variant=self.configuration.get_image_variant()):
                        raise ReleaseInStoreException("Store " + str(u) + " already has this release.")
                except FileNotFoundError:
                    pass

    def build(self):
        # What kind of image are we dealing with?
        if self.configuration.is_installer():
            print("-- Building an installer image")
            print("-- Building the embedded (installable) image first.")
            # Let's build the underlying image, first of all
            image_builder = self.create_image_builder(self.configuration.get_image())

            if image_builder.should_compress():
                print("-- WARNING: Compressed inner images in an installer are not supported! Disabling compression.")
                image_builder.set_should_compress(False)

            self.build_single_image(image_builder)
            installed_image_metadata, installed_image_image = image_builder.get_image_files()

            builder = self.create_image_builder(self.configuration.get_installer())
            builder.prepare_installer_data(installed_image_image)
            self.build_single_image(builder)
            if self.configuration.get_image_version():
                builder.generate_recovery_package()
                recovery_package_metadata, recovery_package_file = builder.get_recovery_package_files()
        else:
            print("-- Building a standalone image")
            builder = self.create_image_builder(self.configuration.get_image())
            self.build_single_image(builder)

        metadata, image = builder.get_image_files()
        if self.configuration.is_installer():
            installer_metadata = metadata
            metadata = installed_image_metadata
            metadata["checksum"] = installer_metadata["checksum"]
            metadata["download_size"] = installer_metadata["download_size"]
            metadata["artifact_type"] = "installer"
            try:
                metadata["compression_format"] = self.configuration.get_installer()["compression_format"]
            except KeyError:
                pass
        else:
            metadata["artifact_type"] = "image"
            try:
                metadata["compression_format"] = self.configuration.get_image()["compression_format"]
            except KeyError:
                pass

        with open(self.configuration.get_full_image_name()+".metadata", "w") as outfile:
            json.dump(metadata, outfile)

        for u in (u for u in self.configuration.get_upload_managers() if u.can_store_images()):
            print("-- Uploading image...")
            u.upload_image(self.configuration.get_image()["name"], self.configuration.get_image()["group"],
                           self.configuration.get_full_image_name() + ".metadata", image,
                           version=self.configuration.get_image_version(),
                           variant=self.configuration.get_image_variant())
            if self.configuration.is_installer() and self.configuration.get_image_version():
                with open(self.configuration.get_full_image_name() + "_recovery.metadata", "w") as outfile:
                    json.dump(recovery_package_metadata, outfile)
                u.upload_recovery_package(self.configuration.get_image()["name"],
                                          self.configuration.get_image()["group"],
                                          self.configuration.get_full_image_name() + "_recovery.metadata",
                                          recovery_package_file,
                                          version=self.configuration.get_image_version(),
                                          variant=self.configuration.get_image_variant())

    def create_image_builder(self, metadata):
        if metadata["type"] == "fs":
            builder = FsImageBuilder(metadata, self.configuration.get_crypto(),
                                     variant=self.configuration.get_image_variant(),
                                     version=self.configuration.get_image_version())
        elif metadata["type"] == "raw":
            builder = RawMultipartImageBuilder(metadata, self.configuration.get_crypto(),
                                               variant=self.configuration.get_image_variant(),
                                               version=self.configuration.get_image_version())
        elif metadata["type"] == "squash":
            builder = SquashImageBuilder(metadata, self.configuration.get_crypto(),
                                         variant=self.configuration.get_image_variant(),
                                         version=self.configuration.get_image_version())
        elif metadata["type"] == "vm":
            print("-- Building a Virtual Machine image")
            builder = VMImageBuilder(metadata, self.configuration.get_crypto(),
                                     variant=self.configuration.get_image_variant(),
                                     version=self.configuration.get_image_version())
        else:
            raise Exception("Unknown image type!")

        self.builders.append(builder)

        return builder

    @staticmethod
    def build_single_image(builder):
        # Build image
        print("-- Building image...")
        builder.build_image()
        if builder.should_compress():
            print("-- Compressing image...")
            builder.compress_image()

    def cleanup(self):
        for b in self.builders:
            shutil.rmtree(b.build_dir)


def build_hemera_image(args_parameter=None):
    parser = argparse.ArgumentParser(description='Hemera Image Builder')
    parser.add_argument('metadata', type=str, help="The image's metadata")
    parser.add_argument('--skip-cleanup', action='store_true',
                        help='Skips the cleanup phase. Warning: this will leave build artifacts around!')
    parser.add_argument('--skip-upload', action='store_true',
                        help='Skips the upload phase. Use for local testing.')
    parser.add_argument('--skip-crypto', action='store_true',
                        help='Skips the crypto instruction. WARNING: Use for local testing only!!')
    parser.add_argument('--skip-sanity-checks', action='store_true',
                        help='Continues even if some sanity checks fail. Do not use in production!')

    if args_parameter:
        args = parser.parse_args(args=args_parameter)
    else:
        args = parser.parse_args()

    print("Hemera Image Builder, version", hemeraplatformsdk.__version__)

    try:
        builder = ImageBuilder(args.metadata, skip_upload=args.skip_upload, skip_crypto=args.skip_crypto)
        builder.build()
        print("-- Image built successfully!")
        if args.skip_cleanup:
            print("-- Not cleaning up, as requested.")
        else:
            print("-- Cleaning up...")
            builder.cleanup()
            print("-- Done.")
    except ReleaseInStoreException as exc:
        print("-- Release is already built. Assuming this was an honest mistake, failing gracefully...")
        exit(0)
    except:
        if args.skip_cleanup:
            print("-- Build failed! Not cleaning up, as requested.")
        else:
            print("-- Build failed! Cleaning up...")
            try:
                builder.cleanup()
                os.remove(builder.configuration.get_full_image_name() + ".metadata")
            except UnboundLocalError:
                # An exception might as well be triggered well before we created a builder.
                pass
            except FileNotFoundError:
                # Metadata might not be there.
                pass

        raise
