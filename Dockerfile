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

FROM common AS preparer
RUN apt-get update \
    && apt-get install -y --no-install-recommends xschem=3.4.4-1 \
    && rm -rf /var/lib/apt/lists/*
USER ubuntu

FROM common AS evaluator
USER ubuntu

FROM common AS simulator
RUN apt-get update \
    && apt-get install -y --no-install-recommends ngspice=42+ds-3build1 \
    && rm -rf /var/lib/apt/lists/*
USER ubuntu

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

FROM common AS extractor
COPY --from=magic-build /opt/magic /opt/magic
ENV PATH=/opt/magic/bin:${PATH}
USER ubuntu

FROM common AS agent
RUN apt-get update \
    && apt-get install -y --no-install-recommends git jq make ripgrep \
    && rm -rf /var/lib/apt/lists/*
RUN curl --fail --show-error --silent --location --retry 3 --retry-all-errors --connect-timeout 20 \
        https://github.com/openai/codex/releases/download/rust-v0.150.1/codex-package-x86_64-unknown-linux-musl.tar.gz \
        --output /tmp/codex.tar.gz \
    && echo '00aba704f029f6dc0d948be407a756e0c97cc840132fd691353b2c6b0a505b17  /tmp/codex.tar.gz' | sha256sum --check \
    && mkdir -p /opt/codex \
    && tar -xzf /tmp/codex.tar.gz -C /opt/codex \
    && rm /tmp/codex.tar.gz \
    && ln -s /opt/codex/bin/codex /usr/local/bin/codex \
    && test -x /opt/codex/bin/codex-code-mode-host \
    && install -d -o ubuntu -g ubuntu /home/ubuntu/.codex
USER ubuntu
RUN codex --version

# Default public development environment. Roles still run in separate containers.
# The narrower targets above remain available for custom toolchain profiles.
FROM agent AS tools
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends ngspice=42+ds-3build1 xschem=3.4.4-1 binutils \
    && rm -rf /var/lib/apt/lists/*
COPY --from=model-compiler /usr/local/bin/openvaf /usr/local/bin/openvaf
COPY --from=model-compiler /usr/local/share/doc/openvaf /usr/local/share/doc/openvaf
COPY --from=magic-build /opt/magic /opt/magic
ENV PATH=/opt/magic/bin:${PATH}
USER ubuntu
