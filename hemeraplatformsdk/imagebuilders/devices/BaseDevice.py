#!/usr/bin/python3


class ExtractedFileTooBigException(Exception):
    def __init__(self, *args, **kwargs):
        Exception.__init__(self, *args, **kwargs)


class WrongPartitionTypeException(Exception):
    def __init__(self, *args, **kwargs):
        Exception.__init__(self, *args, **kwargs)


class BaseDevice:
    def __init__(self, device_dictionary, image_builder):
        self.data = device_dictionary
        self.builder = image_builder

    def can_be_mounted(self):
        raise NotImplementedError

    # Implement only if can_be_mounted is True.
    def get_base_mountpoint(self):
        raise NotImplementedError

    def can_be_packaged(self):
        raise NotImplementedError

    def has_fstab_entries(self):
        raise NotImplementedError

    def needs_file_extraction(self):
        return False

    def target_directory(self):
        raise NotImplementedError

    def create_device(self):
        raise NotImplementedError

    def mount_device(self, base_path):
        raise NotImplementedError

    def unmount_device(self):
        raise NotImplementedError

    def package_target_to_device(self, base_path):
        raise NotImplementedError

    def get_device_files(self):
        raise NotImplementedError

    def get_fstab_entries(self):
        raise NotImplementedError

    def get_installer_actions(self):
        raise NotImplementedError

    def extract_file(self, base_path):
        raise NotImplementedError

    def get_partitions(self):
        raise NotImplementedError
