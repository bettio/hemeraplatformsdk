FROM alpine:3.4
MAINTAINER Dario Freddi <dario.freddi@ispirata.com>

# Create needed directories, install packages and prepare environment
RUN mkdir -p /srv/mer/sdks/sdk/ /root/tools/build-scripts /build-hemeraplatformsdk /root/.ssh && \
apk --no-cache add python3 bash qemu-img gptfdisk gzip xz openssh-client curl \
squashfs-tools e2fsprogs cryptsetup zip parted util-linux && \
python3 -m ensurepip && \
rm -r /usr/lib/python*/ensurepip && \
pip3 --no-cache-dir install --upgrade pip setuptools

# Build parted, mtd-utils and python modules
RUN apk --no-cache add --virtual build-dependencies python3-dev gcc git musl-dev parted-dev libffi-dev openssl-dev make linux-headers lzo-dev util-linux-dev zlib-dev acl-dev && \
pip --no-cache-dir install jsonschema paramiko requests scp version_utils && \
git clone https://github.com/rhinstaller/pyparted.git && cd pyparted && git checkout v3.10.7 && \
python3 setup.py build && python3 setup.py install && cd .. && rm -rf pyparted && \
curl -O ftp://ftp.nsg.net.ru/pub/tarballs/sys-fs/mtd-utils-1.5.2.tar.bz2 && tar xf mtd-utils-1.5.2.tar.bz2 && \
cd mtd-utils-1.5.2 && make && make install && cd .. && rm -rf mtd-utils* && \
apk del build-dependencies

# Import source code
COPY setup.py /build-hemeraplatformsdk/
COPY hemeraplatformsdk/ /build-hemeraplatformsdk/hemeraplatformsdk/
COPY scripts/ /build-hemeraplatformsdk/scripts/
# Get legacy runner tools. FIXME: Remove when everything moves to new infrastructure
COPY legacy-tools/* /root/tools/build-scripts/

# Symlink what matters
RUN ln -s /root/tools/build-scripts/ci-build-device.sh /usr/local/bin/ci-build-device && \
ln -s /root/tools/build-scripts/ci-build-gpt-image.sh /usr/local/bin/ci-build-gpt-image && \
ln -s /root/tools/build-scripts/ci-build-private-image.sh /usr/local/bin/ci-build-private-image && \
ln -s /root/tools/build-scripts/create-update-packages.py /usr/local/bin/create-update-packages && \
ln -s /root/tools/build-scripts/ci-build-virtual-machine.sh /usr/local/bin/ci-build-virtual-machine && \
ln -s /root/tools/build-scripts/create-hemera-squash-package.sh /usr/local/bin/create-hemera-squash-package && \
ln -s /root/tools/build-scripts/ci-hemera-common.sh /usr/local/bin/ci-hemera-common.sh && \
ln -s /root/tools/build-scripts/hemera-build-functions /usr/local/bin/hemera-build-functions && \
ln -s /srv/mer/sdks/sdk/mer-sdk-chroot /usr/local/bin/sdk

# TODO: Add known hosts here

# Install Hemera SDK, mark MerSDK and symlink
RUN cd /srv/mer/sdks/sdk/ && curl http://URL_TO_PLATFORM_SDK/platform-sdk_next.tar.bz2 | tar --numeric-owner -p -xjf -
RUN echo 'MerSDK' | tee /srv/mer/sdks/sdk/etc/MerSDK

# Build our platform SDK
RUN cd /build-hemeraplatformsdk/ && python3 setup.py build && python3 setup.py install && cd - && rm -rf /build-hemeraplatformsdk
