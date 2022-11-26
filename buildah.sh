#! /usr/bin/env bash

DOCKER_BASE=python:3.10.8-alpine3.16
ctr=$(buildah from docker.io/${DOCKER_BASE})
mnt=$(buildah mount "$ctr")
mkdir $mnt/znc/
cp -r src/ $mnt/znc/
cp -r plugins/ $mnt/znc/
cp -r zeronet.py $mnt/znc/
cp -r container-run-with-tor.sh $mnt/znc/
cp -r requirements.txt $mnt/znc/

buildah run $ctr apk add tor gcc libffi-dev musl-dev make openssl g++
buildah run $ctr python3 -m pip install -r /znc/requirements.txt

# reproducibility: erase date from all the copied/installed files
find $mnt/ -exec touch -d @1669459000 -m {} +

buildah umount "$ctr"

# buildah config --entrypoint '["/znc/container-run-with-tor.sh"]' --cmd '' "$ctr"

buildah commit --timestamp 1669459000 "$ctr" znc-tmp
buildah rm "$ctr"
