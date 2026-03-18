#!/bin/bash
set -e

SRC_DIR=/vmangos/core
BUILD_DIR=/vmangos/build
INSTALL_DIR=/vmangos/server
MAX_JOBS=${MAX_JOBS:-4}
NPROC=$(( $(nproc) < MAX_JOBS ? $(nproc) : MAX_JOBS ))

CLIENT_BUILD=${CLIENT_BUILD:-5875}

echo "=== VMaNGOS Build ==="
echo "Source:    $SRC_DIR"
echo "Build:     $BUILD_DIR"
echo "Install:   $INSTALL_DIR"
echo "Threads:   $NPROC"
echo "Client:    $CLIENT_BUILD"
echo ""

mkdir -p "$BUILD_DIR" "$INSTALL_DIR"
cd "$BUILD_DIR"

cmake "$SRC_DIR" \
    -DCMAKE_INSTALL_PREFIX="$INSTALL_DIR" \
    -DSUPPORTED_CLIENT_BUILD="$CLIENT_BUILD" \
    -DUSE_EXTRACTORS=${USE_EXTRACTORS:-0} \
    -DCMAKE_BUILD_TYPE=RelWithDebInfo

make -j"$NPROC"
make install

echo ""
echo "=== Generating Docker config files ==="

cd "$INSTALL_DIR/etc"

for dist_file in *.conf.dist; do
    conf_file="${dist_file%.dist}"
    if [ ! -f "$conf_file" ]; then
        sed 's/127\.0\.0\.1;3306;mangos;mangos/db;3306;mangos;mangos/g' "$dist_file" > "$conf_file"
        echo "Created $conf_file (db host: db)"
    else
        echo "Skipped $conf_file (already exists)"
    fi
done

echo ""
echo "=== Build complete ==="
echo "Binaries:  $INSTALL_DIR/bin/"
echo "Configs:   $INSTALL_DIR/etc/"
