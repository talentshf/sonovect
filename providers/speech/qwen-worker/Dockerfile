FROM python:3.12-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS os-security-build
RUN pip install --no-cache-dir pip==26.2.1 setuptools==84.2.0 wheel==0.48.0
COPY --chmod=644 providers/speech/shared/os-security/build.sh /opt/os-security/build.sh
RUN sh /opt/os-security/build.sh
COPY --chmod=644 providers/speech/shared/os-security/build.py providers/speech/shared/os-security/source-lock.json /opt/os-security/
RUN python /opt/os-security/build.py prepare
RUN python /opt/os-security/build.py build acl
RUN python /opt/os-security/build.py build util-linux
COPY --chmod=644 providers/speech/shared/os-security/patch-ncurses.py /opt/os-security/patch-ncurses.py
RUN python /opt/os-security/patch-ncurses.py
RUN python /opt/os-security/build.py build ncurses
COPY --chmod=644 providers/speech/shared/os-security/install.sh providers/speech/shared/os-security/facts.py /opt/os-security/
RUN python /opt/os-security/build.py finalize
RUN apt-get update && apt-get install -y --no-install-recommends gawk texinfo tcl-dev linux-libc-dev libicu-dev chrpath libcap-dev systemtap-sdt-dev lynx rdfind symlinks netbase gperf libgd-dev
COPY --chmod=644 providers/speech/shared/os-security/additional.py providers/speech/shared/os-security/additional-source-lock.json providers/speech/shared/os-security/zlib-crc.patch /opt/os-security/
RUN python /opt/os-security/additional.py prepare
RUN python /opt/os-security/additional.py build zlib
RUN python /opt/os-security/additional.py build sqlite3
RUN DEB_GCC_VERSION=-14 python /opt/os-security/additional.py build glibc
RUN python /opt/os-security/additional.py finalize
COPY --chmod=644 providers/speech/shared/os-security/install.sh providers/speech/shared/os-security/facts.py providers/speech/shared/os-security/residual_facts.py providers/speech/shared/os-security/minimize.py providers/speech/shared/os-security/advisory-policy.json /os-security/source/recipe/
COPY --chmod=644 Dockerfile /os-security/source/recipe/project.Dockerfile
COPY --chmod=644 providers/speech/shared/os-security/REBUILD.md /os-security/source/recipe/REBUILD.md

FROM python:3.12-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS media-build
COPY --chmod=755 providers/speech/shared/build_media.sh /opt/build_media.sh
RUN /opt/build_media.sh

FROM python:3.12-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS qwen-base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOME=/home/sonovect HF_HOME=/models/huggingface HF_HUB_DISABLE_TELEMETRY=1 NVIDIA_VISIBLE_DEVICES=all NVIDIA_DRIVER_CAPABILITIES=compute,utility
WORKDIR /app
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends ca-certificates=20250419+deb13u1 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pip==26.2.1 setuptools==84.2.0 wheel==0.48.0
RUN --mount=type=cache,id=sonovect-pip-gpu,target=/root/.cache/pip,sharing=locked PIP_CACHE_DIR=/root/.cache/pip pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cu132 && pip install --no-cache-dir --no-deps torchaudio==2.11.0+cpu --index-url https://download.pytorch.org/whl/cpu
COPY --chmod=644 providers/speech/constraints.txt ./constraints.txt
COPY --chmod=644 providers/speech/qwen-worker/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --default-timeout=300 -c constraints.txt -r requirements.lock
COPY --chmod=644 providers/speech/qwen-worker/*.py ./
COPY --chmod=644 providers/speech/shared/*.py ./
COPY --chmod=644 sonovect/_version.py ./sonovect_version.py
COPY --chmod=644 sonovect/assets.py ./sonovect_assets.py
COPY --chmod=644 sonovect/model-catalog.json ./model-catalog.json
RUN groupadd --gid 10001 sonovect && useradd --uid 10001 --gid 10001 --create-home sonovect && mkdir -p /models && chown -R 10001:10001 /home/sonovect /models
FROM qwen-base AS asr-worker
COPY --from=os-security-build /os-security/ /tmp/sonovect-os-security/
RUN SONOVECT_IMAGE_BUILD=1 sh /tmp/sonovect-os-security/source/recipe/install.sh
ARG VERSION=0.1.0
ARG REVISION=uncommitted
LABEL org.opencontainers.image.title="Sonovect qwen-worker" org.opencontainers.image.version=$VERSION org.opencontainers.image.revision=$REVISION org.opencontainers.image.licenses="Apache-2.0"
USER 10001:10001
RUN ["python", "/usr/local/share/sonovect-os-security/source/recipe/facts.py", "--verify"]
EXPOSE 8081
HEALTHCHECK --interval=30s --timeout=12s --start-period=60s --retries=3 CMD ["python", "/app/container_health.py", "8081"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8081", "--no-server-header"]

# Default single-host unit: isolated model processes share one reviewed CUDA closure.
FROM qwen-base AS local-worker
USER root
RUN apt-get update && apt-get install -y --no-install-recommends libmp3lame0 libopus0 libvpx9 && rm -rf /var/lib/apt/lists/*
COPY --from=media-build /out/bin/ /usr/local/bin/
COPY --from=media-build /out/share/ /usr/local/share/
COPY --chmod=644 providers/speech/local-worker/requirements.lock /tmp/local-requirements.lock
RUN pip install --no-cache-dir -c /app/constraints.txt -r /tmp/local-requirements.lock
COPY pyproject.toml README.md LICENSE NOTICE /opt/sonovect/package/
COPY sonovect /opt/sonovect/package/sonovect
RUN pip install --no-cache-dir --no-deps --no-build-isolation /opt/sonovect/package && rm -rf /opt/sonovect/package
COPY --chmod=644 providers/speech/api/*.py /opt/sonovect/providers/provider/
COPY --chmod=644 providers/speech/segmentation-worker/*.py providers/speech/segmentation-worker/pinned-models.json /opt/sonovect/providers/segmentation/
COPY --chmod=644 providers/speech/qwen-worker/*.py /opt/sonovect/providers/asr/
COPY --chmod=644 providers/speech/shared/*.py /opt/sonovect/providers/provider/
COPY --chmod=644 providers/speech/shared/*.py /opt/sonovect/providers/segmentation/
COPY --chmod=644 providers/speech/shared/*.py /opt/sonovect/providers/asr/
COPY --chmod=644 sonovect/_version.py /opt/sonovect/providers/provider/sonovect_version.py
COPY --chmod=644 sonovect/_version.py /opt/sonovect/providers/segmentation/sonovect_version.py
COPY --chmod=644 sonovect/_version.py /opt/sonovect/providers/asr/sonovect_version.py
COPY --chmod=644 sonovect/assets.py /opt/sonovect/providers/segmentation/sonovect_assets.py
COPY --chmod=644 sonovect/assets.py /opt/sonovect/providers/asr/sonovect_assets.py
COPY --chmod=644 sonovect/model-catalog.json /opt/sonovect/providers/segmentation/model-catalog.json
COPY --chmod=644 sonovect/model-catalog.json /opt/sonovect/providers/asr/model-catalog.json
RUN mkdir -p /data /models/segmentation /models/qwen && chown -R 10001:10001 /data /models
RUN ["python", "-c", "import os; from pathlib import Path; root=Path('/opt/sonovect'); root.chmod(0o755); [(Path(d).chmod(0o755)) for d,_,_ in os.walk(root)]"]
COPY --from=os-security-build /os-security/ /tmp/sonovect-os-security/
RUN SONOVECT_IMAGE_BUILD=1 sh /tmp/sonovect-os-security/source/recipe/install.sh
USER 10001:10001
RUN ["python", "-c", "import os; from pathlib import Path; root=Path('/opt/sonovect/providers'); assert all(p.is_file() and os.access(p.parent, os.X_OK) for p in [root/'asr/app.py',root/'segmentation/app.py',root/'provider/app.py'])"]
RUN ["python", "/usr/local/share/sonovect-os-security/source/recipe/facts.py", "--verify"]
ARG VERSION=0.1.0
ARG REVISION=uncommitted
LABEL org.opencontainers.image.version=$VERSION org.opencontainers.image.revision=$REVISION org.opencontainers.image.licenses="Apache-2.0"
ENV SONOVECT_DATA_DIR=/data SONOVECT_PROVIDER_URL=http://127.0.0.1:8080
LABEL org.opencontainers.image.title="Sonovect local Qwen speech worker"
HEALTHCHECK --interval=30s --timeout=15s --start-period=120s --retries=3 CMD ["sonovect-runtime", "qwen", "--check"]
CMD ["sonovect-runtime", "qwen"]
