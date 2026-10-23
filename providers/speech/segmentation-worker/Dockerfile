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

FROM python:3.12-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOME=/home/sonovect HF_HOME=/models/huggingface HF_HUB_DISABLE_TELEMETRY=1
WORKDIR /app
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends ca-certificates=20250419+deb13u1 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pip==26.2.1 setuptools==84.2.0 wheel==0.48.0
RUN --mount=type=cache,id=sonovect-pip-cpu,target=/root/.cache/pip,sharing=locked PIP_CACHE_DIR=/root/.cache/pip pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu && pip install --no-cache-dir --no-deps torchaudio==2.11.0+cpu --index-url https://download.pytorch.org/whl/cpu
COPY --chmod=644 providers/speech/constraints.txt ./constraints.txt
COPY --chmod=644 providers/speech/segmentation-worker/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --default-timeout=300 -c constraints.txt -r requirements.lock
COPY --chmod=644 providers/speech/segmentation-worker/*.py ./
COPY --chmod=644 providers/speech/shared/*.py ./
COPY --chmod=644 providers/speech/segmentation-worker/pinned-models.json ./
ENV MODELSCOPE_CACHE=/models
COPY --chmod=644 sonovect/_version.py ./sonovect_version.py
COPY --chmod=644 sonovect/assets.py ./sonovect_assets.py
COPY --chmod=644 sonovect/model-catalog.json ./model-catalog.json
RUN groupadd --gid 10001 sonovect && useradd --uid 10001 --gid 10001 --create-home sonovect && mkdir -p /models && chown -R 10001:10001 /home/sonovect /models
COPY --from=os-security-build /os-security/ /tmp/sonovect-os-security/
RUN SONOVECT_IMAGE_BUILD=1 sh /tmp/sonovect-os-security/source/recipe/install.sh
ARG VERSION=0.1.0
ARG REVISION=uncommitted
LABEL org.opencontainers.image.title="Sonovect segmentation-worker" org.opencontainers.image.version=$VERSION org.opencontainers.image.revision=$REVISION org.opencontainers.image.licenses="Apache-2.0"
USER 10001:10001
RUN ["python", "/usr/local/share/sonovect-os-security/source/recipe/facts.py", "--verify"]
EXPOSE 8082
HEALTHCHECK --interval=30s --timeout=12s --start-period=60s --retries=3 CMD ["python", "/app/container_health.py", "8082"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8082", "--no-server-header"]
