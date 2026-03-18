FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    git \
    g++ \
    libmysqlclient-dev \
    libssl-dev \
    libtbb-dev \
    libcurl4-openssl-dev \
    zlib1g-dev \
    curl \
    unzip \
    mysql-client \
    python3 \
    && rm -rf /var/lib/apt/lists/*

COPY scripts/ /vmangos/scripts/
RUN chmod +x /vmangos/scripts/*.sh

WORKDIR /vmangos
