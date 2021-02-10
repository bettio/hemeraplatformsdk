#!/usr/bin/python3

import json
import jsonschema
import os

from hemeraplatformsdk.FileUploader import ImageStoreFileUploader, ImageStoreV2FileUploader, SCPFileUploader


# Default stuff
DEFAULT_KEYMAP="us"
DEFAULT_LANGUAGE="en_US"
DEFAULT_TIMEZONE="UTC"
DEFAULT_ROOT_PASSWORD="rootme"


class ImageConfigurationManager:
    def __init__(self, filename, skip_crypto=False, skip_upload=False):
        with open(filename) as data_file:
            self.data = json.load(data_file)

        module_dir = os.path.dirname(os.path.abspath(__file__))
        textfile_path = os.path.join(module_dir, 'hemera-image.jsonschema')
        with open(textfile_path) as data_file:
            jsonschema.validate(self.data, json.load(data_file))

        self.upload_managers = []
        # Create upload managers
        if not skip_upload:
            try:
                for u in self.data["upload"]:
                    if u["type"] == "scp":
                        self.upload_managers.append(SCPFileUploader(u))
                    elif u["type"] == "image_store":
                        self.upload_managers.append(ImageStoreFileUploader(u))
                    elif u["type"] == "image_store_v2":
                        self.upload_managers.append(ImageStoreV2FileUploader(u))
            except KeyError:
                print("-- No uploaders configured. Make sure you're gathering the build artifacts!")

        # Populate defaults
        if "keymap" not in self.data["image"]:
            self.data["image"]["keymap"] = DEFAULT_KEYMAP
        if "language" not in self.data["image"]:
            self.data["image"]["language"] = DEFAULT_LANGUAGE
        if "timezone" not in self.data["image"]:
            self.data["image"]["timezone"] = DEFAULT_TIMEZONE
        if "root_password" not in self.data["image"]:
            self.data["image"]["root_password"] = DEFAULT_ROOT_PASSWORD

        # Verify partitions/devices consistency.
        partition_device = False
        try:
            for p in self.data["image"]["partitions"]:
                if p["mountpoint"] == "/":
                    continue
                if (partition_device and "device" not in p) or \
                    (not partition_device and self.data["image"]["partitions"].index(p) > 0 and "device" in p):
                    raise Exception("When specifying device in the partitions array, every partition must have "
                                    "an associated device!")
                partition_device = "device" in p
        except KeyError:
            pass

        if self.is_installer():
            if "name" not in self.data["installer"]:
                self.data["installer"]["name"] = self.data["image"]["name"] + "_installer"
            if "arch" not in self.data["installer"]:
                self.data["installer"]["arch"] = self.data["image"]["arch"]
            if "group" not in self.data["installer"]:
                self.data["installer"]["group"] = self.data["image"]["group"]
            if "keymap" not in self.data["installer"]:
                self.data["installer"]["keymap"] = self.data["image"]["keymap"]
            if "language" not in self.data["installer"]:
                self.data["installer"]["language"] = self.data["image"]["language"]
            if "timezone" not in self.data["installer"]:
                self.data["installer"]["timezone"] = self.data["image"]["timezone"]
            if "root_password" not in self.data["installer"]:
                self.data["installer"]["root_password"] = self.data["image"]["root_password"]

            # Verify partitions/devices consistency.
            partition_device = False
            try:
                for p in self.data["installer"]["partitions"]:
                    if p["mountpoint"] == "/":
                        continue
                    if ("device" not in p and partition_device) or \
                        ("device" in p and not partition_device and self.data["installer"]["partitions"].index(p) > 0):
                        raise Exception("When specifying device in the partitions array, every partition must have "
                                        "an associated device!")
                    partition_device = "device" in p
            except KeyError:
                pass

        if skip_crypto:
            try:
                self.data.pop("crypto", None)
            except KeyError:
                pass

        # Get GitlabCI environment variables
        self.build_id = os.environ.get("CI_BUILD_ID")
        self.build_ref = os.environ.get("CI_BUILD_REF")
        self.build_ref_name = os.environ.get("CI_BUILD_REF_NAME")
        self.build_tag = os.environ.get("CI_BUILD_TAG")

        # Configure version and variant
        self.full_image_name = self.data["image"]["name"]
        self.image_version = None
        self.image_variant = None
        if self.build_tag:
            if '_' in self.build_tag:
                self.image_variant = self.build_tag.split("_")[0]
                self.image_version = self.build_tag.split("_")[-1]
            else:
                self.image_version = self.build_tag
        elif self.build_ref_name != "master":
            self.image_variant = self.build_ref_name
        if self.image_variant:
            self.full_image_name += "_"+self.image_variant
        if self.image_version:
            self.full_image_name += "-"+self.image_version

        # Output information
        print("--- Image configuration loaded.")
        if self.is_installer():
            print("--- Image Type: Installer,", self.data["installer"]["type"])
            print("--- Installed Image Type:", self.data["image"]["type"])
        else:
            print("--- Image Type: Standalone,", self.data["image"]["type"])

        print("--- Appliance Name:", self.data["image"]["name"])
        print("--- Appliance Version:", self.image_version)
        print("--- Appliance Variant:", self.image_variant)
        print("--- Appliance Arch:", self.data["image"]["arch"])

    def is_installer(self):
        return "installer" in self.data

    def get_image_version(self):
        return self.image_version

    def get_image_variant(self):
        return self.image_variant

    def has_crypto(self):
        return "crypto" in self.data

    def image_is_gpt(self):
        return "gpt" in self.data["image"]["type"]

    def image_is_vm(self):
        return "vm" in self.data["image"]["type"]

    def installer_is_gpt(self):
        if self.is_installer():
            return "gpt" in self.data["installer"]["type"]
        else:
            return False

    def get_image(self):
        return self.data["image"]

    def get_full_image_name(self):
        return self.full_image_name

    def get_installer(self):
        if self.is_installer():
            return self.data["installer"]
        else:
            return None

    def get_crypto(self):
        if self.has_crypto():
            return self.data["crypto"]
        else:
            return None

    def get_upload_managers(self):
        return self.upload_managers
