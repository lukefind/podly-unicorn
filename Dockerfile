# Multi-stage build for combined frontend and backend
ARG BASE_IMAGE=cgr.dev/chainguard/python:latest-dev@sha256:c179c7d8e23caed59a51ff74d4742f8f8d3f16af4c33c40acaf8d3ee07234592
FROM node:24-alpine AS frontend-build

WORKDIR /app

# Copy frontend package files
COPY frontend/package*.json ./
RUN npm ci

# Copy frontend source code
COPY frontend/ ./

# Build frontend assets with explicit error handling
RUN set -e && \
    npm run build && \
    test -d dist && \
    echo "Frontend build successful - dist directory created"

# Backend stage
FROM ${BASE_IMAGE} AS backend

# The Chainguard image defaults to a non-root user. Podly's entrypoint starts as
# root to repair bind-mount ownership, then drops to appuser before Flask starts.
USER root

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ARG CUDA_VERSION=12.6
ARG ROCM_VERSION=7.2
ARG USE_GPU=false
ARG USE_GPU_NVIDIA=${USE_GPU}
ARG USE_GPU_AMD=false
ARG PINNED_PIP_VERSION=26.2.2
ARG PINNED_PIPENV_VERSION=2026.10.2
ARG TORCH_VERSION=2.14.1
ARG TRITON_VERSION=3.8.0
ARG TORCH_CPU_INDEX_URL=https://download.pytorch.org/whl/cpu
ARG TORCH_NVIDIA_INDEX_URL=https://download.pytorch.org/whl/cu126
ARG TORCH_ROCM_INDEX_URL=https://download.pytorch.org/whl/rocm7.2

WORKDIR /app

# Install runtime and build dependencies based on the selected base image.
# The Chainguard dev image currently ships Python 3.15, so replace its generic
# Python packages with the repository's supported Python 3.12 packages first.
RUN set -e && \
    if command -v apk >/dev/null 2>&1; then \
    apk upgrade --no-cache && \
    apk del \
    python-3.15-dev python-3.15-base-dev \
    py3.15-pip py3.15-pip-base py3.15-setuptools \
    python-3.15 python-3.15-runtime python-3.15-base && \
    apk add --no-cache \
    ca-certificates \
    ffmpeg \
    gosu \
    shadow \
    python-3.12 \
    py3.12-pip \
    python-3.12-dev \
    build-base; \
    elif [ -f /etc/debian_version ]; then \
    apt-get update && \
    apt-get install -y ca-certificates && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    gosu \
    python3 \
    python3-pip \
    python-is-python3 \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* ; \
    else \
    echo "Unsupported base image: expected Alpine/Wolfi or Debian" >&2; \
    exit 1; \
    fi && \
    python3 -c 'import sys; assert sys.version_info[:2] == (3, 12), sys.version' && \
    python -c 'import sys; assert sys.version_info[:2] == (3, 12), sys.version'

# Install python3-tomli if Python version is less than 3.11 (separate step for ARM compatibility)
RUN if [ -f /etc/debian_version ]; then \
    PYTHON_MINOR=$(python3 --version 2>&1 | grep -o 'Python 3\.[0-9]*' | cut -d '.' -f2) && \
    if [ "$PYTHON_MINOR" -lt 11 ]; then \
    apt-get update && \
    apt-get install -y python3-tomli && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* ; \
    fi ; \
    fi

# Copy all Pipfiles/lock files
COPY Pipfile Pipfile.lock Pipfile.lite Pipfile.lite.lock ./

# Bootstrap pinned installers outside the distribution's Python packages.
# Ubuntu's apt-managed pip has no RECORD and cannot be force-reinstalled.
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN set -e && \
    python3 -m venv --without-pip /opt/pipenv && \
    python3 -m pip --python /opt/pipenv/bin/python install --no-cache-dir "pip==${PINNED_PIP_VERSION}" && \
    PINNED_PIP_VERSION="${PINNED_PIP_VERSION}" /opt/pipenv/bin/python -c 'import os, pip; assert pip.__version__ == os.environ["PINNED_PIP_VERSION"]' && \
    /opt/pipenv/bin/python -m pip install --no-cache-dir "pipenv==${PINNED_PIPENV_VERSION}"

# Keep application dependencies separate from Pipenv's resolver dependencies.
# LiteLLM's supported filelock 3.x must not constrain virtualenv's filelock 4.x.
RUN python3 -m venv --without-pip /opt/venv && \
    /opt/pipenv/bin/python -m pip --python /opt/venv/bin/python install --no-cache-dir "pip==${PINNED_PIP_VERSION}"
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:/opt/pipenv/bin:${PATH}"

# Set pip timeout and retries for better reliability
ENV PIP_DEFAULT_TIMEOUT=1000
ENV PIP_RETRIES=3
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_NO_CACHE_DIR=1

# Set pipenv configuration for better CI reliability
ENV PIPENV_VENV_IN_PROJECT=1
ENV PIPENV_TIMEOUT=1200

# Install dependencies conditionally based on LITE_BUILD
ARG LITE_BUILD=false
RUN set -e && \
    if [ "${LITE_BUILD}" = "true" ]; then \
    echo "Installing lite dependencies (without Whisper)"; \
    echo "Using lite Pipfile:" && \
    PIPENV_PIPFILE=Pipfile.lite pipenv install --deploy; \
    else \
    echo "Installing full dependencies (including Whisper)"; \
    echo "Using full Pipfile:" && \
    PIPENV_PIPFILE=Pipfile pipenv install --deploy; \
    fi

# Replace the lock-installed generic PyTorch wheel with the selected official
# backend wheel. Resolve its backend-specific runtime dependencies normally;
# pip keeps already-compatible lock-installed common dependencies in place.
# Whisper requires the `triton` distribution on Linux x86_64 independently of
# Torch. Install it first; ROCm Torch then overlays its `triton-rocm` backend.
RUN set -e && \
    if [ "${LITE_BUILD}" != "true" ] && [ "$(uname -m)" = "x86_64" ]; then \
    python3 -m pip install --no-cache-dir \
    "triton==${TRITON_VERSION}" --index-url "${TORCH_CPU_INDEX_URL}"; \
    fi && \
    if [ "${LITE_BUILD}" = "true" ]; then \
    echo "Skipping PyTorch installation in lite mode"; \
    elif [ "${USE_GPU}" = "true" ] || [ "${USE_GPU_NVIDIA}" = "true" ]; then \
    python3 -m pip uninstall --yes torch && \
    python3 -m pip install --no-cache-dir \
    "torch==${TORCH_VERSION}" --index-url "${TORCH_NVIDIA_INDEX_URL}" && \
    TORCH_EXPECTED_VERSION="${TORCH_VERSION}" python3 -c 'import os, torch; assert torch.__version__.split("+", 1)[0] == os.environ["TORCH_EXPECTED_VERSION"]; assert "+cu" in torch.__version__; assert torch.version.cuda is not None; assert torch.version.hip is None'; \
    elif [ "${USE_GPU_AMD}" = "true" ]; then \
    python3 -m pip uninstall --yes torch && \
    python3 -m pip install --no-cache-dir \
    "torch==${TORCH_VERSION}" --index-url "${TORCH_ROCM_INDEX_URL}" && \
    TORCH_EXPECTED_VERSION="${TORCH_VERSION}" python3 -c 'import os, torch; assert torch.__version__.split("+", 1)[0] == os.environ["TORCH_EXPECTED_VERSION"]; assert "+rocm" in torch.__version__; assert torch.version.hip is not None; assert torch.version.cuda is None'; \
    else \
    python3 -m pip uninstall --yes torch && \
    python3 -m pip install --no-cache-dir \
    "torch==${TORCH_VERSION}" --index-url "${TORCH_CPU_INDEX_URL}" && \
    TORCH_EXPECTED_VERSION="${TORCH_VERSION}" python3 -c 'import os, torch; assert torch.__version__.split("+", 1)[0] == os.environ["TORCH_EXPECTED_VERSION"]; assert "+cpu" in torch.__version__; assert torch.version.cuda is None; assert torch.version.hip is None'; \
    fi && \
    python3 -m pip check

# Installers are build tools. Even the latest pip/Pipenv releases bundle older
# urllib3/msgpack copies, so remove them and virtualenv's seed wheels rather
# than shipping vulnerable vendored code beside the patched application.
RUN set -e && \
    base_python="$(python3 -c 'import sys; print(sys._base_executable)')" && \
    python3 -m pip uninstall --yes pip && \
    rm -rf /opt/pipenv && \
    if command -v apk >/dev/null 2>&1; then \
    apk del py3.12-pip py3-pip-wheel; \
    elif [ -f /etc/debian_version ]; then \
    for package in python3-pip python3-setuptools python3-wheel; do \
    if dpkg-query -W -f='${db:Status-Status}' "${package}" 2>/dev/null | grep -qx installed; then \
    DEBIAN_FRONTEND=noninteractive apt-get purge -y "${package}"; \
    fi; \
    done; \
    fi && \
    if "${base_python}" -c 'import pip' 2>/dev/null; then \
    "${base_python}" -m pip uninstall --yes pip; \
    fi && \
    "${base_python}" -c 'import importlib.util; assert importlib.util.find_spec("pip") is None' && \
    python3 -c 'import importlib.util; assert importlib.util.find_spec("pip") is None; assert importlib.util.find_spec("pipenv") is None'

# The canonical Chainguard base is a development image so dependencies can be
# compiled. Remove its build-only toolchain after all Python wheels are ready.
RUN if command -v apk >/dev/null 2>&1; then \
    apk del \
    build-base \
    binutils \
    gcc \
    glibc-2.44-dev \
    git \
    libstdc++-dev \
    libxcrypt-dev \
    linux-headers \
    make \
    openssf-compiler-options \
    pkgconf \
    posix-cc-wrappers \
    python-3.12-dev \
    uv \
    wget && \
    ! command -v gcc && \
    ! command -v make && \
    ! apk info -e python-3.12-dev; \
    fi

# Copy application code
COPY src/ ./src/
RUN rm -rf ./src/instance
COPY scripts/ ./scripts/

# Copy built frontend assets to Flask static folder
COPY --from=frontend-build /app/dist ./src/app/static

# Create non-root user for running the application
RUN groupadd -r appuser && \
    useradd --no-log-init -r -g appuser -d /home/appuser appuser && \
    mkdir -p /home/appuser && \
    chown -R appuser:appuser /home/appuser

# Create necessary directories and set permissions
RUN mkdir -p /app/processing /app/src/instance /app/src/instance/data /app/src/instance/data/in /app/src/instance/data/srv /app/src/instance/config /app/src/instance/db && \
    chown -R appuser:appuser /app

# Copy entrypoint script
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod 755 /docker-entrypoint.sh

EXPOSE 5001

# Run the application through the entrypoint script
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python3", "-u", "src/main.py"]
