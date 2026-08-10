#!/bin/bash -eu

export PYTHONPATH="${SRC}${PYTHONPATH:+:${PYTHONPATH}}"

compile_python_fuzzer "$SRC/fuzz/atlas_bundle_fuzzer.py"

sanitizer_lib_dir="$(python3 -c "import atheris; print(atheris.path())")"
case "${SANITIZER:-address}" in
  address)
    cp "${sanitizer_lib_dir}/asan_with_fuzzer.so" "$OUT/sanitizer_with_fuzzer.so"
    ;;
  undefined)
    cp "${sanitizer_lib_dir}/ubsan_with_fuzzer.so" "$OUT/sanitizer_with_fuzzer.so"
    ;;
  coverage | introspector)
    # Coverage and introspector builds do not preload a sanitizer library.
    ;;
  *)
    echo "Unsupported SANITIZER for Python fuzzing: ${SANITIZER}" >&2
    exit 1
    ;;
esac

cp "$(command -v llvm-symbolizer)" "$OUT/llvm-symbolizer"

seed_dir="$SRC/seed_corpora/atlas_bundle_fuzzer"
if compgen -G "$seed_dir/*" > /dev/null; then
  zip -j "$OUT/atlas_bundle_fuzzer_seed_corpus.zip" "$seed_dir/"*
fi
