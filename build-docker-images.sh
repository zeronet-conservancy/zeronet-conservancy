#!/bin/sh
set -e

prefix="${1:-local/}"

for dokerfile in dockerfiles/Dockerfile.* ; do
    suffix="`echo "$dokerfile" | sed 's/.*\/Dockerfile\.//'`"
    image_name="${prefix}zeronet:$suffix"
    echo "DOCKER BUILD $image_name"
    docker build -f "$dokerfile" -t "$image_name" .
done
