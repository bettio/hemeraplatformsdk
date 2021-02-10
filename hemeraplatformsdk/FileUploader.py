#!/usr/bin/python3

import io
import json
import os
from json import JSONDecodeError

import paramiko
import scp
import requests
import time

lastTimeCalled = [0.0]


class StoreNotAvailableException(Exception):
    def __init__(self, *args, **kwargs):
        Exception.__init__(self, *args, **kwargs)


class FileUploader:
    def __init__(self, metadata):
        self.data = metadata
        # Manage host depending on environment variables
        try:
            self.host = os.environ[self.data["host"]]
        except KeyError:
            self.host = self.data["host"]

    def check_store_has_image(self, name, group, version=None, variant=None):
        raise StoreNotAvailableException("Storage " + self.data["type"] + " does not support listing files.")

    def get_old_versions_from_store(self, name, group, variant=None):
        raise StoreNotAvailableException("Storage " + self.data["type"] + " does not support listing old versions.")

    def can_store_images(self):
        return False

    def can_store_updates(self):
        return False

    def upload_image(self, name, group, metadata, image, version=None, variant=None):
        raise StoreNotAvailableException("Storage " + self.data["type"] + " does not support storing images.")

    def upload_recovery_package(self, name, group, metadata, package, version, variant=None):
        raise StoreNotAvailableException("Storage " + self.data["type"] + " does not support storing recovery packages.")

    def upload_file(self, src, dest):
        raise StoreNotAvailableException("Storage " + self.data["type"] + " does not support storing files.")

    def upload_update_package(self, name, group, metadata, package, version, variant=None):
        raise StoreNotAvailableException("Storage " + self.data["type"] + " does not support storing updates.")

    def upload_recovery_package(self, name, group, metadata, package, version, variant=None):
        raise StoreNotAvailableException("Storage " + self.data["type"] + " does not support storing recovery packages.")


def scp_upload_progress_callback(filename, size, sent):
    # TODO: As soon as we find a decent way to use it.
    pass
    # print("--- Upload in progress, {}%".format(int((sent / size) * 100)))


class SCPFileUploader(FileUploader):
    def __init__(self, metadata):
        super().__init__(metadata)
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.load_system_host_keys()
        # Environment variables?
        if "SSH_PRIVATE_KEY" in os.environ:
            # Get key from os.environ
            keyfile = io.StringIO(os.environ["SSH_PRIVATE_KEY"])
            pkey = paramiko.RSAKey.from_private_key(keyfile)
            self.client.connect(self.host, username=self.data["user"], pkey=pkey)
        elif "privatekey" in self.data:
            if "privatekey_password" in self.data:
                pkey = paramiko.RSAKey.from_private_key_file(filename=self.data["privatekey"],
                                                             password=self.data["privatekey_password"])
            else:
                pkey = paramiko.RSAKey.from_private_key_file(filename=self.data["privatekey"])
            self.client.connect(self.host, username=self.data["user"], pkey=pkey)
        elif "password" in self.data:
            self.client.connect(self.host, username=self.data["user"], password=self.data["password"])
        else:
            self.client.connect(self.host, username=self.data["user"])

    def can_store_images(self):
        return True

    def can_store_updates(self):
        return False

    def check_store_has_image(self, name, group, version=None, variant=None):
        check_path = os.path.join(self.data["base_upload_path"], group, name)
        if version:
            check_path = os.path.join(check_path, "releases", version)

        if variant:
            image_wildcard = name + "_" + variant + "*"
        else:
            image_wildcard = name + "*"

        check_path = os.path.join(check_path, image_wildcard)

        _, stdout, _ = self.client.exec_command("[ -f " + check_path + " ] && echo OK")

        if stdout.read():
            return True
        else:
            return False

    def get_old_versions_from_store(self, name, group, variant=None):
        old_versions = []
        match_string = name
        if variant:
            match_string += "_" + variant
        with paramiko.SFTPClient.from_transport(self.client.get_transport()) as sftp:
            dirs = sftp.listdir(os.path.join(self.data["base_upload_path"], group, name, "releases"))
            for d in dirs:
                files = sftp.listdir(os.path.join(self.data["base_upload_path"], group, name, "releases", d))
                for f in files:
                    if match_string + "-" + d in f and ".metadata" in f:
                        mf = sftp.file(os.path.join(self.data["base_upload_path"], group, name, "releases", d, f))
                        metadata = mf.read()
                        try:
                            old_versions.append((d, json.loads(metadata)))
                        except JSONDecodeError:
                            print("---- WARNING: Failed to retrieve metadata for {}! "
                                  "Metadata is malformed. Skipping...".format(f))
                        break

        return old_versions

    def upload_image(self, name, group, metadata, image, version=None, variant=None):
        upload_path = os.path.join(self.data["base_upload_path"], group, name)
        if version:
            upload_path = os.path.join(upload_path, "releases", version)
        # Create directory first
        self.client.exec_command("mkdir -p " + upload_path)

        # Go
        self.upload_file(metadata, os.path.join(upload_path, metadata.split('/')[-1]))
        self.upload_file(image, os.path.join(upload_path, image.split('/')[-1]))

    def upload_recovery_package(self, name, group, metadata, package, version, variant=None):
        upload_path = os.path.join(self.data["base_upload_path"], group, name, "releases", version)
        # Create directory first
        self.client.exec_command("mkdir -p " + upload_path)

        # Go
        self.upload_file(metadata, os.path.join(upload_path, metadata.split('/')[-1]))
        self.upload_file(package, os.path.join(upload_path, package.split('/')[-1]))

    def upload_update_package(self, name, group, metadata, package, version, variant=None):
        upload_path = os.path.join(self.data["base_upload_path"], group, name, "releases", version)
        # Create directory first
        self.client.exec_command("mkdir -p " + upload_path)

        # Go
        self.upload_file(metadata, os.path.join(upload_path, metadata.split('/')[-1]))
        self.upload_file(package, os.path.join(upload_path, package.split('/')[-1]))

    def upload_file(self, src, dest):
        print("---- Uploading", src, "to", self.host, "...")

        try:
            with scp.SCPClient(self.client.get_transport(), progress=scp_upload_progress_callback) as scp_client:
                scp_client.put(src, os.path.join(self.data["base_upload_path"], dest))
        except scp.SCPException:
            if "metadata" in src:
                print("WARNING: Could not upload metadata. This could be normal behavior if no uploaders requiring "
                      "metadata have been configured.")
            else:
                raise


class ImageStoreFileUploader(FileUploader):
    def __init__(self, metadata):
        super().__init__(metadata)

        try:
            self.verify_ssl = self.data["verify_ssl"]
            if not self.verify_ssl:
                print("WARNING: The Server's SSL certificate will be trusted regardless. "
                      "This should only be used when testing!!")
        except KeyError:
            # Always verify SSL by default!
            self.verify_ssl = True

    def can_store_images(self):
        return True

    def can_store_updates(self):
        return True

    def get_old_versions_from_store(self, name, group, variant=None):
        print("---- Getting old versions from ImageStore endpoint", self.host, "...")

        try:
            appliance_name = name + "_" + variant
        except:
            appliance_name = name

        r = requests.get('{}/images/{}'.format(self.host, appliance_name),
                         verify=self.verify_ssl,
                         headers={'X-API-Key': self.data["api_key"]})

        if r.status_code != 200:
            print("---- Getting versions failed! Return code: ", r.status_code, r.text)
            raise Exception("Getting versions failed", r.text)

        try:
            return json.loads(r.text)
        except JSONDecodeError:
            raise Exception("Getting versions failed - message malformed", r.text)

    def check_store_has_image(self, name, group, version=None, variant=None):
        try:
            appliance_name = name + "_" + variant
        except:
            appliance_name = name

        r = requests.options('{}/images/{}/{}'.format(self.host, appliance_name, version if version else 'rolling'),
                             verify=self.verify_ssl,
                             headers={'X-API-Key': self.data["api_key"]})

        if r.status_code != 200:
            raise FileNotFoundError("Image not available in store!")

        try:
            return json.loads(r.text)
        except JSONDecodeError:
            raise FileNotFoundError("Image not available in store!")

    def upload_image(self, name, group, metadata, image, version=None, variant=None):
        print("---- Uploading image payload to ImageStore endpoint", self.host, "...")

        try:
            appliance_name = name + "_" + variant
        except:
            appliance_name = name

        payload = {'metadata': open(metadata, 'r'), 'image': open(image, 'rb')}

        r = requests.post('{}/images/{}/{}'.format(self.host, appliance_name, version if version else 'rolling'),
                          files=payload, verify=self.verify_ssl,
                          headers={'X-API-Key': self.data["api_key"]})

        if r.status_code != 200:
            print("---- Upload failed! Return code: ", r.status_code, r.text)
            raise Exception("Upload failed", r.text)

    def upload_recovery_package(self, name, group, metadata, package, version, variant=None):
        print("---- Uploading recovery package to ImageStore endpoint", self.host, "...")

        try:
            appliance_name = name + "_" + variant
        except:
            appliance_name = name

        payload = {'metadata': open(metadata, 'r'), 'package': open(package, 'rb')}

        r = requests.post('{}/updates/{}/{}'.format(self.host, appliance_name, version), files=payload,
                          verify=self.verify_ssl,
                          headers={'X-API-Key': self.data["api_key"]})

        if r.status_code != 200:
            print("---- Upload failed! Return code: ", r.status_code, r.text)
            raise Exception("Upload failed", r.text)

        print("---- Upload successful!")

    def upload_update_package(self, name, group, metadata, package, version, variant=None):
        print("---- Uploading update package to ImageStore endpoint", self.host, "...")

        try:
            appliance_name = name + "_" + variant
        except:
            appliance_name = name

        payload = {'metadata': open(metadata, 'r'), 'package': open(package, 'rb')}

        r = requests.post('{}/updates/{}/{}'.format(self.host, appliance_name, version), files=payload,
                          verify=self.verify_ssl,
                          headers={'X-API-Key': self.data["api_key"]})

        if r.status_code != 200:
            print("---- Upload failed! Return code: ", r.status_code, r.text)
            raise Exception("Upload failed", r.text)

        print("---- Upload successful!")


class ImageStoreV2FileUploader(FileUploader):
    def __init__(self, metadata):
        super().__init__(metadata)
        self.organization = self.data["organization"]

        try:
            self.verify_ssl = self.data["verify_ssl"]
            if not self.verify_ssl:
                print("WARNING: The Server's SSL certificate will be trusted regardless. "
                      "This should only be used when testing!!")
        except KeyError:
            # Always verify SSL by default!
            self.verify_ssl = True

    def can_store_images(self):
        return True

    def can_store_updates(self):
        return True

    def get_old_versions_from_store(self, name, group, variant=None):
        print("---- Getting old versions from ImageStore endpoint", self.host, "...")

        try:
            appliance_name = name + "_" + variant
        except:
            appliance_name = name

        r = requests.get('{}/api/v1/{}/images/{}'.format(self.host, self.organization, appliance_name),
                         verify=self.verify_ssl,
                         headers={'Authorization': self.data["api_key"]})

        if r.status_code != 200:
            print("---- Getting versions failed! Return code: ", r.status_code, r.text)
            raise Exception("Getting versions failed", r.text)

        try:
            return json.loads(r.text)
        except JSONDecodeError:
            raise Exception("Getting versions failed - message malformed", r.text)

    def check_store_has_image(self, name, group, version=None, variant=None):
        try:
            appliance_name = name + "_" + variant
        except:
            appliance_name = name

        r = requests.options('{}/api/v1/{}/images/{}/{}'.format(self.host, self.organization,
                                                                appliance_name, version if version else 'rolling'),
                             verify=self.verify_ssl,
                             headers={'Authorization': self.data["api_key"]})

        if r.status_code != 200:
            raise FileNotFoundError("Image not available in store!")

        try:
            return json.loads(r.text)
        except JSONDecodeError:
            raise FileNotFoundError("Image not available in store!")

    def upload_image(self, name, group, metadata, image, version=None, variant=None):
        print("---- Uploading image payload to ImageStore endpoint", self.host, "...")

        try:
            appliance_name = name + "_" + variant
        except:
            appliance_name = name

        payload = {'metadata': open(metadata, 'r'), 'package': open(image, 'rb')}

        r = requests.post('{}/api/v1/{}/images/{}/{}'.format(self.host, self.organization,
                                                             appliance_name, version if version else 'rolling'),
                          files=payload, verify=self.verify_ssl,
                          headers={'Authorization': self.data["api_key"]})

        if r.status_code != 200:
            print("---- Upload failed! Return code: ", r.status_code, r.text)
            raise Exception("Upload failed", r.text)

    def upload_recovery_package(self, name, group, metadata, package, version, variant=None):
        print("---- Uploading recovery package to ImageStore endpoint", self.host, "...")

        try:
            appliance_name = name + "_" + variant
        except:
            appliance_name = name

        payload = {'metadata': open(metadata, 'r'), 'package': open(package, 'rb')}

        r = requests.post('{}/api/v1/{}/updates/{}/{}'.format(self.host, self.organization,
                                                              appliance_name, version), files=payload,
                          verify=self.verify_ssl,
                          headers={'Authorization': self.data["api_key"]})

        if r.status_code != 200:
            print("---- Upload failed! Return code: ", r.status_code, r.text)
            raise Exception("Upload failed", r.text)

        print("---- Upload successful!")

    def upload_update_package(self, name, group, metadata, package, version, variant=None):
        print("---- Uploading update package to ImageStore endpoint", self.host, "...")

        try:
            appliance_name = name + "_" + variant
        except:
            appliance_name = name

        payload = {'metadata': open(metadata, 'r'), 'package': open(package, 'rb')}

        r = requests.post('{}/api/v1/{}/updates/{}/{}'.format(self.host, self.organization,
                                                              appliance_name, version), files=payload,
                          verify=self.verify_ssl,
                          headers={'Authorization': self.data["api_key"]})

        if r.status_code != 200:
            print("---- Upload failed! Return code: ", r.status_code, r.text)
            raise Exception("Upload failed", r.text)

        print("---- Upload successful!")
