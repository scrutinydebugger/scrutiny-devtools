#!/bin/bash
SCRIPT_DIR=$(realpath $( dirname "${BASH_SOURCE[0]}" ))
cd $SCRIPT_DIR

SCRUTINY_MAIN="../../scrutiny-main"

if [ ! -d "${SCRUTINY_MAIN}" ]; then
    echo "Don't know where is scrutiny-main"
fi

set -x
rm -rf output
python make_icons.py dark --output output/dark
python make_icons.py light --output output/light

rm -rf "${SCRUTINY_MAIN}/scrutiny/gui/assets/icons/dark"
mv output/dark "${SCRUTINY_MAIN}/scrutiny/gui/assets/icons/dark"

rm -rf "${SCRUTINY_MAIN}/scrutiny/gui/assets/icons/light"
mv output/light "${SCRUTINY_MAIN}/scrutiny/gui/assets/icons/light"
