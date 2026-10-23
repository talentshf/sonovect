#!/bin/sh
set -eu
# Build only the media paths this service and its synthetic fixtures need.
# Release signature fingerprint: FCF986EA15E6E293A5644F10B4322F04D67658D8.
VERSION=9.0.2
SHA256=8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e
apt-get update
apt-get upgrade -y
apt-get install -y --no-install-recommends build-essential pkg-config nasm curl ca-certificates xz-utils libmp3lame-dev libopus-dev libvpx-dev
mkdir -p /tmp/media-source /out/bin /out/share/sonovect-media
cd /tmp/media-source
curl --fail --location --retry 3 --output ffmpeg.tar.xz "https://ffmpeg.org/releases/ffmpeg-${VERSION}.tar.xz"
printf '%s  %s\n' "$SHA256" ffmpeg.tar.xz | sha256sum --check -
tar -xf ffmpeg.tar.xz
cd "ffmpeg-${VERSION}"
./configure --disable-everything --disable-autodetect --disable-doc --disable-debug --disable-network \
    --enable-static --disable-shared --enable-ffmpeg --enable-ffprobe \
    --enable-libmp3lame --enable-libopus --enable-libvpx \
    --enable-protocol=file,pipe \
    --enable-demuxer=wav,mp3,flac,ogg,mov,matroska,aac,aiff,avi \
    --enable-muxer=wav,mp3,flac,ipod,adts,ogg,aiff,mov,mp4,matroska,webm,avi \
    --enable-decoder='pcm*' --enable-decoder=aac,mp3,mp3float,flac,vorbis,opus,alac,wrapped_avframe \
    --enable-parser=aac,aac_latm,mpegaudio,flac,opus,vorbis \
    --enable-encoder=pcm_s16le,pcm_s16be,flac,aac,mpeg4,ffv1,libmp3lame,libopus,libvpx_vp8 \
    --enable-indev=lavfi \
    --enable-filter=color,sine,anullsrc,asetpts,aresample,adelay,aformat,anull,format,scale,abuffer,abuffersink,buffer,buffersink
make -j4
install -m755 ffmpeg ffprobe /out/bin/
cp ../ffmpeg.tar.xz /out/share/sonovect-media/ffmpeg-${VERSION}.tar.xz
cp COPYING.LGPLv2.1 /out/share/sonovect-media/
cp /opt/build_media.sh /out/share/sonovect-media/build_media.sh
/out/bin/ffmpeg -version > /out/share/sonovect-media/version.txt
/out/bin/ffmpeg -L > /out/share/sonovect-media/license.txt 2>&1
