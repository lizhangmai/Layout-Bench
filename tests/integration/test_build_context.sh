#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
test_tmp="$(mktemp -d "${TMPDIR:-/tmp}/layout-bench-context.XXXXXX")"
trap 'rm -rf "${test_tmp}"' EXIT
context="${test_tmp}/context"
mkdir -p "${context}/.cache" "${context}/.codex" \
    "${context}/tasks" "${context}/results" "${context}/benchmarking" \
    "${context}/third_party/example"
cp "${repo_root}/.dockerignore" "${context}/.dockerignore"
printf 'FROM scratch\nCOPY . /\n' > "${context}/Dockerfile"

allowed=(
    pyproject.toml
    uv.lock
)
blocked=(
    .codex/auth.json
    .codex/config.toml
    .cache/private.bin
    tasks/private.json
    results/final.gds
    benchmarking/private.py
    third_party/example/reference.gds
    .gitmodules
    main.py
    .env
)
for path in "${allowed[@]}" "${blocked[@]}"; do
    printf 'context test fixture\n' > "${context}/${path}"
done

docker build --quiet --file "${context}/Dockerfile" \
    --output "type=local,dest=${test_tmp}/export" "${context}"
for path in "${allowed[@]}"; do
    test -f "${test_tmp}/export/${path}"
done
for path in "${blocked[@]}"; do
    if [[ -e "${test_tmp}/export/${path}" ]]; then
        echo "Unexpected build input: ${path}" >&2
        exit 1
    fi
done
echo 'PASS: build context allows dependency files and excludes credentials, caches, tasks, results, and third-party sources'
