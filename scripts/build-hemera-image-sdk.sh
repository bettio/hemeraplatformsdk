#!/bin/bash

# External arguments
IMAGE_NAME="${1}"
IMAGE_TYPE="${2}"
IMAGE_ARCH="${3}"
MIC_CACHE_DIR="/parentroot${4}"
BUILD_DIR="${5}"
KICKSTART_FILE="${6}"
MIC_EXTRA_ARGS="${7}"

echo "[ =SDK= ] BUILD_DIR.....: ${BUILD_DIR}"
echo "[ =SDK= ] IMAGE_ARCH....: ${IMAGE_ARCH}"
echo "[ =SDK= ] IMAGE_NAME....: ${IMAGE_NAME}"
echo "[ =SDK= ] IMAGE_TYPE....: ${IMAGE_TYPE}"
echo "[ =SDK= ] KICKSTART_FILE: ${KICKSTART_FILE}"
echo "[ =SDK= ] MIC_CACHE_DIR.: ${MIC_CACHE_DIR}"
echo "[ =SDK= ] MIC_EXTRA_ARGS: ${MIC_EXTRA_ARGS}"
echo "[ =SDK= ] PWD...........: ${PWD}"

# Let's do the work
cd ${BUILD_DIR}

if [ "${IMAGE_TYPE}" == "raw" ]; then
  mic create ${IMAGE_TYPE} ${KICKSTART_FILE} -o ${IMAGE_NAME} --cachedir=${MIC_CACHE_DIR} --record-pkgs=name --pkgmgr=zypp --arch=${IMAGE_ARCH} ${MIC_EXTRA_ARGS}
elif [ "${IMAGE_TYPE}" == "squash" ]; then
  # Create a pure fs with no packing, then squash will process it. Do not put additional mic args here!
  mic create fs ${KICKSTART_FILE} -o ${IMAGE_NAME} --cachedir=${MIC_CACHE_DIR} --record-pkgs=name --pkgmgr=zypp --arch=${IMAGE_ARCH}
else
  mic create ${IMAGE_TYPE} ${KICKSTART_FILE} --pack-to=${IMAGE_NAME}.tar -o ${IMAGE_NAME} --cachedir=${MIC_CACHE_DIR} --record-pkgs=name --pkgmgr=zypp --arch=${IMAGE_ARCH} ${MIC_EXTRA_ARGS}
fi

RETURN_VALUE=$?
exit ${RETURN_VALUE}
