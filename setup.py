#! /usr/bin/python3
# encoding: utf-8

import os
import sys
import subprocess
from distutils.core import setup, Command
from distutils.extension import Extension
from distutils.version import StrictVersion, LooseVersion
from hemeraplatformsdk import __version_info__ as vers
from setuptools import setup, find_packages

script_path = os.path.dirname(os.path.abspath(__file__))


# hemeraplatformsdk version (change in hemeraplatformsdk/__init__.py)
RELEASE = "%d.%d.%d" % (vers[0], vers[1], vers[2])
VERSION = "%d.%d" % (vers[0], vers[1] if vers[2] < 99 else vers[1] + 1)

# Add git commit count for dev builds
if vers[2] == 99:
    try:
        call = subprocess.Popen(
            ["git", "log", "--oneline"], stdout=subprocess.PIPE)
        out, err = call.communicate()
    except Exception:
        RELEASE += "a0"
    else:
        log = out.decode("utf-8").strip()
        if log:
            ver = log.count("\n")
            RELEASE += "a" + str(ver)
        else:
            RELEASE += "a0"

# === Sphinx ===
try:
    from sphinx.setup_command import BuildDoc
except ImportError:
    class BuildDoc(Command):
        description = \
            "build documentation using sphinx, that must be installed."
        user_options = []

        def initialize_options(self):
            pass

        def finalize_options(self):
            pass

        def run(self):
            print("Error: sphinx not found")

setup(
    name="hemeraplatformsdk",
    fullname="Hemera Platform SDK",
    description="A set of classes for building Hemera images and updates",
    version=RELEASE,
    author=(
        "Ispirata"
        ),
    author_email="info@ispirata.com",
    maintainer="Ispirata S.r.l.",
    maintainer_email="info@ispirata.com",
    contact="Hemera support team",
    contact_email="hemera@ispirata.com",
    url="http://hemera.io",
    license="Apache 2.0",
    cmdclass={"build_doc": BuildDoc},
    command_options={
        'build_doc': {
            'version': ('setup.py', VERSION),
            'release': ('setup.py', RELEASE)
        }
    },
    packages = find_packages(),
    package_data = {
        # Copy needed files for package
        '': ['kickstart-template.ks', '*.jsonschema']
    },
    requires=["jsonschema", "parted", "requests", "paramiko", "ratelimit", "scp", "version_utils"],
    scripts=["scripts/mkhemerasquashfs", "scripts/build-hemera-image-sdk.sh"],
    entry_points={
        'console_scripts': [
            'build-hemera-image = hemeraplatformsdk.ImageBuilder:build_hemera_image',
            'create-hemera-update-packages = hemeraplatformsdk.UpdatePackageGenerator:create_hemera_update_packages'
        ]
    }
)
