#!/usr/bin/env bash
set -uo pipefail

usage() {
  echo "Usage: $0 OPE-NNN [-- verification-command ...]" >&2
}

if [[ $# -lt 1 || ! $1 =~ ^OPE-[0-9]+$ ]]; then
  usage
  exit 2
fi

issue_number=${1#OPE-}
shift
output_dir="/tmp/ope${issue_number}-hugo-build"
hugo_bin=${HUGO_BIN:-hugo}

if [[ $# -gt 0 ]]; then
  if [[ $1 != -- || $# -lt 2 ]]; then
    usage
    exit 2
  fi
  shift
fi

cleanup_on_success=false
finish() {
  status=$?
  if [[ $status -eq 0 && $cleanup_on_success == true ]]; then
    rm -rf -- "$output_dir" || status=$?
  elif [[ -d $output_dir ]]; then
    echo "Hugo verification failed; preserving evidence at $output_dir" >&2
  fi
  exit "$status"
}
trap finish EXIT

export HUGO_OUTPUT_DIR=$output_dir
"$hugo_bin" --gc --minify --cleanDestinationDir --destination "$output_dir" || exit $?

if [[ $# -gt 0 ]]; then
  "$@" || exit $?
fi

cleanup_on_success=true
echo "Hugo verification passed; removing scratch output $output_dir"
