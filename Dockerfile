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

FROM python:3.12-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS package-build
RUN pip install --no-cache-dir pip==26.2.1 setuptools==84.2.0 wheel==0.48.0
WORKDIR /source
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY sonovect ./sonovect
RUN pip wheel --no-deps --no-build-isolation --wheel-dir /wheels .

FROM python:3.12-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS runtime-base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 HOME=/home/sonovect SONOVECT_DATA_DIR=/data
WORKDIR /app
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends ca-certificates=20250419+deb13u1 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pip==26.2.1 setuptools==84.2.0 wheel==0.48.0
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
RUN groupadd --gid 10001 sonovect && useradd --uid 10001 --gid 10001 --create-home sonovect \
    && mkdir -p /data /models && chown -R 10001:10001 /home/sonovect /data /models
USER 10001:10001

FROM runtime-base AS media-base
USER root
RUN apt-get update && apt-get install -y --no-install-recommends libmp3lame0 libopus0 libvpx9 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=media-build /out/bin/ /usr/local/bin/
COPY --from=media-build /out/share/ /usr/local/share/
USER 10001:10001

FROM media-base AS native-dependencies
USER root
COPY --chmod=644 providers/speech/constraints.txt ./constraints.txt
COPY --chmod=644 providers/speech/native-worker/requirements.lock ./providers-native.lock
RUN --mount=type=cache,id=sonovect-pip-cpu,target=/root/.cache/pip,sharing=locked PIP_CACHE_DIR=/root/.cache/pip pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir --no-deps torchaudio==2.11.0+cpu --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -c constraints.txt -r providers-native.lock
USER 10001:10001
ENV MODELSCOPE_CACHE=/models/modelscope HF_HOME=/models/huggingface

FROM runtime-base AS core
USER root
COPY --from=package-build /wheels/ /tmp/sonovect-wheels/
RUN pip install --no-cache-dir --no-index --no-deps /tmp/sonovect-wheels/*.whl && rm -rf /tmp/sonovect-wheels
COPY --from=os-security-build /os-security/ /tmp/sonovect-os-security/
RUN SONOVECT_IMAGE_BUILD=1 sh /tmp/sonovect-os-security/source/recipe/install.sh
USER 10001:10001
RUN ["python", "/usr/local/share/sonovect-os-security/source/recipe/facts.py", "--verify"]
ARG VERSION=0.1.0
ARG REVISION=uncommitted
LABEL org.opencontainers.image.title="Sonovect" org.opencontainers.image.version=$VERSION org.opencontainers.image.revision=$REVISION org.opencontainers.image.licenses="Apache-2.0" org.opencontainers.image.description="Self-hosted ASR for audio and video soundtracks, with separate sound analysis."
EXPOSE 8096
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 CMD ["sonovect-health", "api"]
CMD ["uvicorn", "sonovect.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8096", "--no-server-header"]

FROM media-base AS media-worker
USER root
COPY --from=package-build /wheels/ /tmp/sonovect-wheels/
RUN pip install --no-cache-dir --no-index --no-deps /tmp/sonovect-wheels/*.whl && rm -rf /tmp/sonovect-wheels
COPY --from=os-security-build /os-security/ /tmp/sonovect-os-security/
RUN SONOVECT_IMAGE_BUILD=1 sh /tmp/sonovect-os-security/source/recipe/install.sh
USER 10001:10001
RUN ["python", "/usr/local/share/sonovect-os-security/source/recipe/facts.py", "--verify"]
ARG VERSION=0.1.0
ARG REVISION=uncommitted
LABEL org.opencontainers.image.title="Sonovect media worker" org.opencontainers.image.version=$VERSION org.opencontainers.image.revision=$REVISION org.opencontainers.image.licenses="Apache-2.0"
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 CMD ["sonovect-health", "worker"]
CMD ["sonovect-worker"]

FROM native-dependencies AS funasr-worker
USER root
COPY --from=package-build /wheels/ /tmp/sonovect-wheels/
RUN pip install --no-cache-dir --no-index --no-deps /tmp/sonovect-wheels/*.whl && rm -rf /tmp/sonovect-wheels
COPY --from=os-security-build /os-security/ /tmp/sonovect-os-security/
RUN SONOVECT_IMAGE_BUILD=1 sh /tmp/sonovect-os-security/source/recipe/install.sh
USER 10001:10001
RUN ["python", "/usr/local/share/sonovect-os-security/source/recipe/facts.py", "--verify"]
ARG VERSION=0.1.0
ARG REVISION=uncommitted
LABEL org.opencontainers.image.title="Sonovect native worker" org.opencontainers.image.version=$VERSION org.opencontainers.image.revision=$REVISION org.opencontainers.image.licenses="Apache-2.0"
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 CMD ["sonovect-health", "worker"]
CMD ["sonovect-worker"]

FROM native-dependencies AS vocal-worker
USER root
COPY --from=package-build /wheels/ /tmp/sonovect-wheels/
RUN pip install --no-cache-dir --no-index --no-deps /tmp/sonovect-wheels/*.whl && rm -rf /tmp/sonovect-wheels
COPY --chmod=644 providers/speech/vocal-worker/*.py /app/
COPY --chmod=644 providers/speech/shared/runtime_config.py providers/speech/shared/container_health.py /app/
COPY --chmod=644 sonovect/assets.py /app/sonovect_assets.py
COPY --chmod=644 sonovect/model-catalog.json /app/model-catalog.json
COPY --from=os-security-build /os-security/ /tmp/sonovect-os-security/
RUN SONOVECT_IMAGE_BUILD=1 sh /tmp/sonovect-os-security/source/recipe/install.sh
USER 10001:10001
RUN ["python", "/usr/local/share/sonovect-os-security/source/recipe/facts.py", "--verify"]
ARG VERSION=0.1.0
ARG REVISION=uncommitted
LABEL org.opencontainers.image.title="Sonovect experimental CPU vocal worker" org.opencontainers.image.version=$VERSION org.opencontainers.image.revision=$REVISION org.opencontainers.image.licenses="Apache-2.0"
EXPOSE 8085
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 CMD ["python", "/app/container_health.py", "8085"]
CMD ["uvicorn", "vocal_app:app", "--host", "0.0.0.0", "--port", "8085", "--no-server-header"]

FROM runtime-base AS measurements-worker
USER root
COPY --chmod=644 providers/speech/constraints.txt ./constraints.txt
COPY --chmod=644 providers/speech/measurement-worker/requirements.lock ./measurement-requirements.lock
RUN pip install --no-cache-dir -c constraints.txt -r measurement-requirements.lock
COPY --from=package-build /wheels/ /tmp/sonovect-wheels/
RUN pip install --no-cache-dir --no-index --no-deps /tmp/sonovect-wheels/*.whl && rm -rf /tmp/sonovect-wheels
COPY --chmod=644 providers/speech/measurement-worker/*.py /app/
COPY --chmod=644 providers/speech/shared/runtime_config.py providers/speech/shared/container_health.py /app/
COPY --from=os-security-build /os-security/ /tmp/sonovect-os-security/
RUN SONOVECT_IMAGE_BUILD=1 sh /tmp/sonovect-os-security/source/recipe/install.sh
USER 10001:10001
RUN ["python", "/usr/local/share/sonovect-os-security/source/recipe/facts.py", "--verify"]
ARG VERSION=0.1.0
ARG REVISION=uncommitted
LABEL org.opencontainers.image.title="Sonovect weight-free measurements" org.opencontainers.image.version=$VERSION org.opencontainers.image.revision=$REVISION org.opencontainers.image.licenses="Apache-2.0"
ENV OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 NUMBA_CACHE_DIR=/tmp/numba-cache
EXPOSE 8086
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 CMD ["python", "/app/container_health.py", "8086"]
CMD ["uvicorn", "measurement_app:app", "--host", "0.0.0.0", "--port", "8086", "--no-server-header"]

# No model framework or weights in the measurements-only compact analysis image.
FROM measurements-worker AS analysis-measurements
USER root

COPY --chmod=644 providers/speech/measurement-worker/*.py /opt/sonovect/providers/measurements/
COPY --chmod=644 providers/speech/shared/runtime_config.py providers/speech/shared/container_health.py /opt/sonovect/providers/measurements/

RUN ["python", "-c", "import os; from pathlib import Path; root=Path('/opt/sonovect'); root.chmod(0o755); [(Path(d).chmod(0o755)) for d,_,_ in os.walk(root)]"]
USER 10001:10001
RUN ["python", "-c", "import os; from pathlib import Path; p=Path('/opt/sonovect/providers/measurements/measurement_app.py'); assert p.is_file() and os.access(p.parent, os.X_OK)"]
LABEL org.opencontainers.image.title="Sonovect local numerical analysis"
HEALTHCHECK --interval=30s --timeout=12s --start-period=60s --retries=3 CMD ["sonovect-runtime", "analysis", "--check"]
CMD ["sonovect-runtime", "analysis"]

# Only enabled analysis processes start; models remain lazy and downloaded separately.
FROM native-dependencies AS analysis-worker
USER root
COPY --from=package-build /wheels/ /tmp/sonovect-wheels/
RUN pip install --no-cache-dir --no-index --no-deps /tmp/sonovect-wheels/*.whl && rm -rf /tmp/sonovect-wheels
COPY --chmod=644 providers/speech/event-worker/requirements.lock /tmp/event-requirements.lock
RUN pip install --no-cache-dir -c /app/constraints.txt -r /tmp/event-requirements.lock
COPY --chmod=644 providers/speech/event-worker/*.py /opt/sonovect/providers/events/
COPY --chmod=644 providers/speech/vocal-worker/*.py /opt/sonovect/providers/vocal/
COPY --chmod=644 providers/speech/shared/*.py /opt/sonovect/providers/events/
COPY --chmod=644 providers/speech/shared/*.py /opt/sonovect/providers/vocal/
COPY --chmod=644 sonovect/_version.py /opt/sonovect/providers/events/sonovect_version.py
COPY --chmod=644 sonovect/assets.py /opt/sonovect/providers/events/sonovect_assets.py
COPY --chmod=644 sonovect/assets.py /opt/sonovect/providers/vocal/sonovect_assets.py
COPY --chmod=644 sonovect/model-catalog.json /opt/sonovect/providers/events/model-catalog.json
COPY --chmod=644 sonovect/model-catalog.json /opt/sonovect/providers/vocal/model-catalog.json

COPY --chmod=644 providers/speech/measurement-worker/*.py /opt/sonovect/providers/measurements/
COPY --chmod=644 providers/speech/shared/runtime_config.py providers/speech/shared/container_health.py /opt/sonovect/providers/measurements/

RUN ["python", "-c", "import os; from pathlib import Path; root=Path('/opt/sonovect'); root.chmod(0o755); [(Path(d).chmod(0o755)) for d,_,_ in os.walk(root)]"]
COPY --from=os-security-build /os-security/ /tmp/sonovect-os-security/
RUN SONOVECT_IMAGE_BUILD=1 sh /tmp/sonovect-os-security/source/recipe/install.sh
USER 10001:10001
RUN ["python", "-c", "import os; from pathlib import Path; root=Path('/opt/sonovect/providers'); assert all(p.is_file() and os.access(p.parent, os.X_OK) for p in [root/'events/app.py',root/'vocal/vocal_app.py',root/'measurements/measurement_app.py'])"]
RUN ["python", "/usr/local/share/sonovect-os-security/source/recipe/facts.py", "--verify"]
ARG VERSION=0.1.0
ARG REVISION=uncommitted
LABEL org.opencontainers.image.title="Sonovect local CPU analysis" org.opencontainers.image.version=$VERSION org.opencontainers.image.revision=$REVISION org.opencontainers.image.licenses="Apache-2.0"
ENV OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 NUMBA_CACHE_DIR=/tmp/numba-cache
HEALTHCHECK --interval=30s --timeout=12s --start-period=90s --retries=3 CMD ["sonovect-runtime", "analysis", "--check"]
CMD ["sonovect-runtime", "analysis"]
