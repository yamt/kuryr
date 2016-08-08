#!/bin/bash -e

for guide in developer-guide install-guide ops-guide; do
    directory="doc/${guide}"
    build_dir="${directory}/build/html"
    doctrees="${build_dir}.doctrees"
    set -x
    sphinx-build -E -d ${doctrees} -b html \
        ${directory}/source ${build_dir}
    set +x
done
