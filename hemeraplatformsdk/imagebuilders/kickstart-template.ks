#
# Kickstart for @APPLIANCE_NAME@
#

# Language, keyboard and timezone
lang @LANG@
keyboard @KEYMAP@
timezone --utc @TIMEZONE@
@BOOTLOADER@

# Partitions
@PARTITIONS@

# Users
rootpw @ROOT_PASSWORD@

# Repos
@REPOSITORIES@

%packages
@PACKAGES@

%end

%post

# Add versioning information. Needed for updates!
cat << EOF >> /etc/hemera/appliance_manifest
APPLIANCE_NAME=@APPLIANCE_NAME@
APPLIANCE_VARIANT=@APPLIANCE_VARIANT@
APPLIANCE_VERSION=@APPLIANCE_VERSION@
EOF

# Add remount information. Needed for remount-helper.
cat << EOF >> /etc/hemera/gravity/remount.conf
@REMOUNT_LIST@
EOF

# Only for cross targets!
if [[ ! @ARCH@ == *86* ]]; then
    # Without this line the rpm don't get the architecture right.
    echo -n '@ARCH@-meego-linux' > /etc/rpm/platform

    if [[ -f /etc/zypp/zypp.conf ]]; then
        # Also libzypp has problems in autodetecting the architecture so we force tha as well.
        # https://bugs.meego.com/show_bug.cgi?id=11484
        echo 'arch = @ARCH@' >> /etc/zypp/zypp.conf
    fi
fi

# Rebuild db using target's rpm
echo -n "Remove rpm db.."
rm -f /var/lib/rpm/__db*
echo "done"

# Copy and preserve rpm DB into /usr/local/lib/rpm/ . This allows tmpfiles to do its job and create
# the correct RPM DB upon wiping /var/lib/rpm after installation
mkdir -p /usr/local/lib/rpm/
cp -a /var/lib/rpm/* /usr/local/lib/rpm/

# Create /recovery, needed by Hemera's internals
mkdir -p /recovery

# Enable serial login
@SERIAL_LOGIN@

@INTERNAL_POST_SCRIPTS@
@CUSTOM_POST_SCRIPTS@

%end

%post --nochroot

@COPY_COMMANDS@
@INTERNAL_POST_NOCHROOT_SCRIPTS@
@CUSTOM_POST_NOCHROOT_SCRIPTS@

%end
