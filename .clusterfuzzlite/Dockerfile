FROM gcr.io/oss-fuzz-base/base-builder-python:v1@sha256:53a670f691b0bd348aa9f97a512918611ed960132c0fc124a12c2bc49ddec20a

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

COPY .clusterfuzzlite/requirements.txt /tmp/metriplane-fuzz-requirements.txt
RUN python -m pip install \
      --no-cache-dir \
      --only-binary=:all: \
      --require-hashes \
      -r /tmp/metriplane-fuzz-requirements.txt

COPY metriplane $SRC/metriplane
COPY fuzz/clusterfuzzlite/atlas_bundle_fuzzer.py $SRC/fuzz/atlas_bundle_fuzzer.py
COPY .clusterfuzzlite/seed_corpora $SRC/seed_corpora
COPY --chmod=755 .clusterfuzzlite/build.sh $SRC/build.sh

WORKDIR $SRC
