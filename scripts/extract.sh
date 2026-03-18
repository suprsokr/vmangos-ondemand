#!/bin/bash
set -e

DATA_DIR=/vmangos/data
WOW_DIR=${WOW_DIR:-/wow}
BIN_DIR=/vmangos/server/bin
EXTRACTOR_DIR=/vmangos/server/bin/Extractors
SRC_DIR=/vmangos/core
STEPS=${EXTRACT_STEPS:-all}
CLIENT_BUILD=${CLIENT_BUILD:-5875}

echo "=== VMaNGOS Data Extraction ==="
echo "WoW client: $WOW_DIR"
echo "Client build: $CLIENT_BUILD"
echo "Output:     $DATA_DIR"
echo "Steps:      $STEPS"
echo ""

if [ ! -d "$WOW_DIR/Data" ]; then
    echo "ERROR: WoW Data/ directory not found at $WOW_DIR/Data"
    echo "Make sure you mounted the WoW client directory correctly."
    exit 1
fi

if [ ! -f "$EXTRACTOR_DIR/MapExtractor" ]; then
    echo "Extractors not found in $EXTRACTOR_DIR, building with USE_EXTRACTORS=1..."
    mkdir -p /vmangos/build
    cd /vmangos/build
    cmake "$SRC_DIR" \
        -DCMAKE_INSTALL_PREFIX=/vmangos/server \
        -DSUPPORTED_CLIENT_BUILD=${CLIENT_BUILD:-5875} \
        -DUSE_EXTRACTORS=1 \
        -DCMAKE_BUILD_TYPE=RelWithDebInfo
    make -j"$(nproc)"
    make install
    echo ""
fi

mkdir -p "$DATA_DIR"
cd "$DATA_DIR"

rm -rf "$DATA_DIR/Data"
ln -sf "$WOW_DIR/Data" "$DATA_DIR/Data"

if [ "$STEPS" = "all" ] || [ "$STEPS" = "maps" ]; then
    echo "=== Step 1: Extracting maps and DBC files ==="
    "$EXTRACTOR_DIR/MapExtractor"
    # mangosd expects DBC in ./<build>/dbc/ (client build subdir)
    mkdir -p "$DATA_DIR/$CLIENT_BUILD"
    rm -f "$DATA_DIR/$CLIENT_BUILD/dbc"
    ln -sf ../dbc "$DATA_DIR/$CLIENT_BUILD/dbc"
    echo ""
fi

if [ "$STEPS" = "all" ] || [ "$STEPS" = "vmaps" ]; then
    echo "=== Step 2: Extracting vmaps ==="
    "$EXTRACTOR_DIR/VMapExtractor"
    echo ""
    echo "=== Step 3: Assembling vmaps ==="
    mkdir -p vmaps
    "$EXTRACTOR_DIR/VMapAssembler" Buildings vmaps
    rm -rf Buildings
    echo ""
fi

if [ "$STEPS" = "all" ] || [ "$STEPS" = "mmaps" ]; then
    echo "=== Step 4: Generating movement maps (this will take hours) ==="
    mkdir -p mmaps
    OFFMESH_ARG=""
    [ -f "$EXTRACTOR_DIR/offmesh.txt" ] && OFFMESH_ARG="--offMeshInput $EXTRACTOR_DIR/offmesh.txt"
    "$EXTRACTOR_DIR/MoveMapGenerator" $OFFMESH_ARG
    echo ""
fi

rm -f "$DATA_DIR/Data"

echo "=== Extraction complete ==="
echo "Contents of $DATA_DIR:"
ls -la "$DATA_DIR"
