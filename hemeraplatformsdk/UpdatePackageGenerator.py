#!/usr/bin/python3

import argparse
import errno
import os
import json
from version_utils import rpm
import shutil
import subprocess
import tempfile
import hashlib
import sys

from hemeraplatformsdk.ImageConfigurationManager import ImageConfigurationManager
from hemeraplatformsdk.imagebuilders.BaseImageBuilder import MIC_CACHE_DIR


def sha1checksum(filename):
    sha1 = hashlib.sha1()

    with open(filename, 'rb') as f:
        while True:
            data = f.read(65536)
            if not data:
                break
            sha1.update(data)

    return sha1.hexdigest()


# Put some helpers for yum rpmUtils.
def string_to_version(verstring):
    if verstring in [None, '']:
        return (None, None, None)
    i = verstring.find(':')
    if i != -1:
        try:
            epoch = str(long(verstring[:i]))
        except ValueError:
            # look, garbage in the epoch field, how fun, kill it
            epoch = '0' # this is our fallback, deal
    else:
        epoch = '0'
    j = verstring.find('-')
    if j != -1:
        if verstring[i + 1:j] == '':
            version = None
        else:
            version = verstring[i + 1:j]
        release = verstring[j + 1:]
    else:
        if verstring[i + 1:] == '':
            version = None
        else:
            version = verstring[i + 1:]
        release = None
    return epoch, version, release


def split_filename(filename):
    """
    Pass in a standard style rpm fullname

    Return a name, arch, epoch, version, release e.g.::
        foo-1.0-1.i386.rpm returns foo, 1.0, 1, i386
        1:bar-9-123a.ia64.rpm returns bar, 9, 123a, 1, ia64
    """

    if filename[-4:] == '.rpm':
        filename = filename[:-4]

    archIndex = filename.rfind('.')
    arch = filename[archIndex+1:]

    relIndex = filename[:archIndex].rfind('-')
    rel = filename[relIndex+1:archIndex]

    verIndex = filename[:relIndex].rfind('-')
    ver = filename[verIndex+1:relIndex]

    epochIndex = filename.find(':')
    if epochIndex == -1:
        epoch = ''
    else:
        epoch = filename[:epochIndex]

    name = filename[epochIndex + 1:verIndex]
    return name, arch, epoch, ver, rel


def compare_version(v1, r1, v2, r2):
    # return 1: a is newer than b
    # 0: a and b are the same version
    # -1: b is newer than a
    v1 = str(v1)
    r1 = str(r1)
    v2 = str(v2)
    r2 = str(r2)
    #print '%s, %s, %s vs %s, %s, %s' % (e1, v1, r1, e2, v2, r2)
    rc = rpm.compare_versions(v1+"-"+r1, v2+"-"+r2)
    #print '%s, %s, %s vs %s, %s, %s = %s' % (e1, v1, r1, e2, v2, r2, rc)
    return rc


def packages_to_dictionary(packages):
    packages_dict = {}
    for package in packages:
        package_tuple = package, split_filename(package)
        packages_dict[package_tuple[1][0]] = package_tuple[1][3:], package_tuple[0]

    return packages_dict


def generate_squash_package(image_crypto, dir, filename, remove_uid_gid=True):
    process_env = os.environ.copy()
    if remove_uid_gid:
        process_env["ADDITIONAL_MKSQUASHFS_ARGS"] = "-force-uid 0 -force-gid 0"
    squash_call = ["mkhemerasquashfs", dir, filename]
    try:
        squash_call.append(image_crypto["key"])
    except TypeError:
        # No Crypto specified
        pass
    except KeyError:
        pass

    subprocess.check_call(squash_call, env=process_env)

    # Add additional crypto keys
    try:
        print("--- Adding {} additional LUKS keys".format(len(image_crypto["additional_keys"])))
        with tempfile.TemporaryDirectory() as tempdir:
            subprocess.check_call(["/sbin/losetup", "/dev/loop7", tempdir])
            for additional_key in image_crypto["additional_keys"]:
                proc = subprocess.Popen(["/sbin/cryptsetup", "luksAddKey", "/dev/loop7"], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, universal_newlines=True)
                proc.stdin.write(image_crypto["key"] + "\n")
                proc.stdin.write(additional_key + "\n")
                proc.stdin.write(additional_key + "\n")
                proc.communicate()
                if proc.returncode != 0:
                    subprocess.check_call(["/sbin/losetup", "-d" "/dev/loop7"])
                    raise Exception("luksAddKey failed!")

            subprocess.check_call(["/sbin/losetup", "-d" "/dev/loop7"])
    except (KeyError, TypeError):
        # No additional keys
        pass


class UpdatePackageGenerator:
    def __init__(self, configuration, new_release, old_release, packages_dir):
        self.data = configuration
        self.appliance_name = configuration.get_full_image_name()
        self.new_release = new_release
        self.old_release = old_release
        self.build_dir = os.path.join(os.getcwd(), "build-" + configuration.get_full_image_name())
        self.packages_dir = packages_dir
        self.new_packages = {}
        self.old_packages = {}
        self.install_packages = []
        self.remove_packages = []

        self.base_package_name = "{}_update_{}_{}".format(self.appliance_name,
                                                          old_release["version"], new_release["version"])

    def read_packages(self):
        self.new_packages = packages_to_dictionary(self.new_release["packages"])
        self.old_packages = packages_to_dictionary(self.old_release["packages"])

    def populate_package_list(self):
        # Verify what's up here.
        for k,v in iter(self.new_packages.items()):
            if k in self.old_packages:
                oldVersion = self.old_packages[k][0]
                newVersion = v[0]

                if compare_version(newVersion[0], newVersion[1], oldVersion[0], oldVersion[1]) > 0:
                    self.install_packages.append(v[1])
            else:
                self.install_packages.append(v[1])

        # Do we need to remove any packages?
        for k in iter(self.old_packages.keys()):
            if not k in self.new_packages:
                # We have to remove this package
                self.remove_packages.append(k)

        print("---- New/Updated packages:", len(self.install_packages))
        print("---- Removed packages:", len(self.remove_packages))

    def create_package(self):
        # Step 1: Create dir
        with tempfile.TemporaryDirectory() as temp_dir:
            # Step 2: Assemble packages
            for p in self.install_packages:
                p_found = False
                for root, dirs, files in os.walk(self.packages_dir):
                    for f in files:
                        if p in f:
                            package = os.path.join(root, f)
                            print("---- Copying RPM package:", package)
                            shutil.copy(package, temp_dir)
                            p_found = True
                            break
                if not p_found:
                    raise IOError("File not found ", p)

            # Step 3: Create manifest for packages to be removed
            if self.remove_packages:
                removeDict = { "remove_packages": self.remove_packages }
                with open(os.path.join(temp_dir, "remove.json"), 'w') as outfile:
                    json.dump(removeDict, outfile)

            # Step 4: Create basic metadata
            try:
                metadata_dict = {
                    "from_version": self.old_release["version"],
                    "version": self.new_release["version"],
                    "appliance_name": self.appliance_name,
                    "artifact_type": "update"
                }
                with open(os.path.join(temp_dir, "metadata"), 'w') as outfile:
                    json.dump(metadata_dict, outfile)
            except:
                raise

            # Step 5: Create SquashFS
            print("---- Creating update package...")
            generate_squash_package(self.data.get_crypto(), temp_dir,
                                    os.path.join(self.build_dir, self.base_package_name + ".hpd"))

        # Step 6: Create full metadata
        try:
            metadata_dict["download_size"] = os.path.getsize(os.path.join(self.build_dir,
                                                                          self.base_package_name + ".hpd"))
            metadata_dict["checksum"] = sha1checksum(os.path.join(self.build_dir, self.base_package_name + ".hpd"))
            with open(os.path.join(self.build_dir, self.base_package_name + ".metadata"), 'w') as outfile:
                json.dump(metadata_dict, outfile)
        except:
            os.remove(os.path.join(self.build_dir, self.base_package_name + ".hpd"))
            raise

    def get_update_package(self):
        return os.path.join(self.build_dir, self.base_package_name + ".metadata"),\
               os.path.join(self.build_dir, self.base_package_name + ".hpd")


def create_hemera_update_packages(args_parameter=None):
    parser = argparse.ArgumentParser(description='Hemera Update Package generator')
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

    # Create ImageConfigurationManager
    configuration = ImageConfigurationManager(args.metadata)
    assert configuration.get_image_version()

    major_version = int(configuration.get_image_version().split('.')[0])

    build_dir = os.path.join(os.getcwd(), "build-" + configuration.get_full_image_name())

    try:
        os.makedirs(build_dir)
    except OSError as exc:
        if exc.errno == errno.EEXIST and os.path.isdir(build_dir):
            pass
        else:
            raise

    if configuration.get_image_variant():
        print("-- Generating incremental update packages for", configuration.get_image()["name"], "variant",
              configuration.get_image_variant(), "to version", configuration.get_image_version())
    else:
        print("-- Generating incremental update packages for", configuration.get_image()["name"],
              "to version", configuration.get_image_version())

    # Actual uploaders!
    actual_uploaders = [u for u in configuration.get_upload_managers() if u.can_store_updates()]
    if not actual_uploaders:
        print("-- Apparently, your image metadata specifies no uploaders capable of storing updates. "
              "There's no way I can generate packages locally! Exiting gracefully...")
        sys.exit(0)

    # Get old releases
    for u in actual_uploaders:
        # Get information about current image.
        try:
            current_release_metadata = u.check_store_has_image(configuration.get_image()["name"],
                                                               configuration.get_image()["group"],
                                                               version=configuration.get_image_version(),
                                                               variant=configuration.get_image_variant())
        except FileNotFoundError:
            print("-- Uploader {} does not have image {} version {}. Continuing..."
                  .format(str(u), configuration.get_image()["name"], configuration.get_image_version()))
            continue

        print("-- Generating updates for uploader {}".format(str(u)))
        old_versions = u.get_old_versions_from_store(configuration.get_image()["name"],
                                                     configuration.get_image()["group"],
                                                     variant=configuration.get_image_variant())

        if not old_versions:
            print("-- Apparently, that was the only release available. "
                  "All is fine, see you next time, then I'll have work to do!")
            continue

        for metadata in old_versions:
            if metadata["version"] == "rolling" or metadata["version"] == current_release_metadata["version"]:
                continue
            # We generate update packages only if the major version is the same.
            if int(metadata["version"].split('.')[0]) != major_version:
                continue

            # Verify if the version is actually newer. We do not want to accidentally generate downgrade packages!
            if compare_version(configuration.get_image_version(), "", metadata["version"], "") < 1:
                print("-- Version {} was found as a release, but it is newer than {}. Skipping."
                      .format(metadata["version"], configuration.get_image_version()))
                continue
            print("-- Generating package {} -> {}".format(metadata["version"],
                                                          configuration.get_image_version()))
            generator = UpdatePackageGenerator(configuration,
                                               new_release=current_release_metadata,
                                               old_release=metadata, packages_dir=MIC_CACHE_DIR)

            # Do it!
            try:
                generator.read_packages()
                generator.populate_package_list()
                generator.create_package()

                print("-- Update package created successfully!")

                # Upload now
                if not args.skip_upload:
                    update_metadata, update_package = generator.get_update_package()
                    u.upload_update_package(configuration.get_image()["name"], configuration.get_image()["group"],
                                            update_metadata, update_package,
                                            version=configuration.get_image_version(),
                                            variant=configuration.get_image_variant())
            except Exception as err:
                print("Package creation failed!")
                raise
