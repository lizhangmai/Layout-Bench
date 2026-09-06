# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:0.11.2 AS uv
FROM ubuntu:24.04 AS common

ENV DEBIAN_FRONTEND=noninteractive \
    UV_PROJECT_ENVIRONMENT=/opt/layout-bench-tools \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    PATH=/opt/layout-bench-tools/bin:${PATH} \
    QT_QPA_PLATFORM=offscreen

RUN test "$(dpkg --print-architecture)" = amd64 \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl python3 python3-venv python3-tk \
    && rm -rf /var/lib/apt/lists/*

RUN curl --fail --show-error --silent --location --retry 3 --retry-all-errors --connect-timeout 20 \
        https://www.klayout.org/downloads/Ubuntu-24/klayout_0.30.11-1_amd64.deb \
        --output /tmp/klayout.deb \
    && echo '772eb2c597dc8ec054800841246fcbf6f3440581caee53663dc93afd135027b3  /tmp/klayout.deb' | sha256sum --check \
    && apt-get update \
    && apt-get install -y --no-install-recommends /tmp/klayout.deb \
    && rm /tmp/klayout.deb \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock /opt/layout-bench-build/
RUN --mount=type=cache,target=/root/.cache/uv \
    cd /opt/layout-bench-build \
    && uv sync --locked --only-group eda --no-install-project --python /usr/bin/python3 \
    && install -d -o ubuntu -g ubuntu /workspace

WORKDIR /workspace
CMD ["bash"]

FROM common AS qucsator-build
ARG QUCSATOR_COMMIT=e995f9acc71a8c7319286944e4a1692318b9dd80
ARG QUCSATOR_SHA256=ee77425b6714b14ee8ac2ba5c33709c00802fd3cdc1f6519cf5d7df033644964
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential cmake flex bison gperf adms \
    && rm -rf /var/lib/apt/lists/*
RUN curl --fail --show-error --silent --location --retry 3 --retry-all-errors --connect-timeout 20 \
        "https://codeload.github.com/Qucs/qucsator/tar.gz/${QUCSATOR_COMMIT}" \
        --output /tmp/qucsator.tar.gz \
    && echo "${QUCSATOR_SHA256}  /tmp/qucsator.tar.gz" | sha256sum --check \
    && tar -xzf /tmp/qucsator.tar.gz -C /tmp \
    && cmake -S "/tmp/qucsator-${QUCSATOR_COMMIT}" -B /tmp/qucsator-build \
        -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/qucsator \
    && cmake --build /tmp/qucsator-build --parallel 4 \
    && cmake --install /tmp/qucsator-build \
    && rm -rf /tmp/qucsator.tar.gz "/tmp/qucsator-${QUCSATOR_COMMIT}" /tmp/qucsator-build

FROM common AS model-compiler
RUN apt-get update \
    && apt-get install -y --no-install-recommends binutils \
    && rm -rf /var/lib/apt/lists/*
RUN curl --fail --show-error --silent --location --retry 3 --retry-all-errors --connect-timeout 20 \
        https://fides.fe.uni-lj.si/openvaf/download/openvaf-reloaded-osdi_0.3-31-gf47d557-linux_x64.tar.gz \
        --output /tmp/openvaf.tar.gz \
    && echo '9bc343d52e00529ddba452b90358cdd14da14ec7437d75dec2dbd621eda54bc8  /tmp/openvaf.tar.gz' | sha256sum --check \
    && tar -xzf /tmp/openvaf.tar.gz -C /usr/local/bin openvaf \
    && rm /tmp/openvaf.tar.gz \
    && install -D /usr/share/common-licenses/GPL-3 /usr/local/share/doc/openvaf/COPYING
USER ubuntu

FROM common AS magic-build
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential tcl-dev tk-dev libx11-dev zlib1g-dev libreadline-dev \
    && rm -rf /var/lib/apt/lists/*
RUN curl --fail --show-error --silent --location --retry 3 --retry-all-errors --connect-timeout 20 \
        https://codeload.github.com/RTimothyEdwards/magic/tar.gz/refs/tags/8.3.678 \
        --output /tmp/magic.tar.gz \
    && echo '3f47b68d3ca2c0ef1cdf18916581a5ac3a529ecc83c6ad0d7cd8e1800d2c3614  /tmp/magic.tar.gz' | sha256sum --check \
    && tar -xzf /tmp/magic.tar.gz -C /tmp \
    && cd /tmp/magic-8.3.678 \
    && ./configure --prefix=/opt/magic --without-opengl --without-cairo --disable-magic-builddate \
    && make -j4 \
    && make install \
    && install -D LICENSE /opt/magic/share/doc/LICENSE

# The public development environment is one image. Every preparation, solver,
# and judge container is an isolated invocation of this same EDA toolchain.
# Harness runtimes are supplied by the harness (or its selected image); the
# benchmark image does not install or privilege a particular Agent framework.
FROM common AS tools
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends git jq make ripgrep \
        ngspice=42+ds-3build1 xschem=3.4.4-1 binutils \
    && rm -rf /var/lib/apt/lists/*
ARG QUCS_S_VERSION=26.1.1-1
ARG QUCS_S_SHA256=580c3cf5aa7f99bf76ee49822317633c46649aebec2f64f83fb52a2db8b45fab
RUN curl --fail --show-error --silent --location --retry 3 --retry-all-errors --connect-timeout 20 \
        "https://download.opensuse.org/repositories/home:/ra3xdh/xUbuntu_24.04/amd64/qucs-s_${QUCS_S_VERSION}_amd64.deb" \
        --output /tmp/qucs-s.deb \
    && echo "${QUCS_S_SHA256}  /tmp/qucs-s.deb" | sha256sum --check \
    && apt-get update \
    && apt-get install -y --no-install-recommends /tmp/qucs-s.deb \
    && rm /tmp/qucs-s.deb \
    && rm -rf /var/lib/apt/lists/*
COPY --from=qucsator-build /opt/qucsator /opt/qucsator
ENV PATH=/opt/qucsator/bin:${PATH}
RUN test -x /usr/bin/qucs-s \
    && test -x /opt/qucsator/bin/qucsator \
    && test -x /usr/bin/qucsator_rf \
    && test -x /opt/qucsator/bin/qucsconv
COPY --from=model-compiler /usr/local/bin/openvaf /usr/local/bin/openvaf
COPY --from=model-compiler /usr/local/share/doc/openvaf /usr/local/share/doc/openvaf
COPY --from=magic-build /opt/magic /opt/magic
ENV PATH=/opt/magic/bin:${PATH}
USER ubuntu
