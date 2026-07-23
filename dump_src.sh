#!/bin/bash

# version: 2.6.0 (bugfixes + cleanup)

set -euo pipefail

# --- Color setup ---
if [[ -t 1 ]]; then
  RED="\033[0;31m"
  GREEN="\033[0;32m"
  YELLOW="\033[0;33m"
  BLUE="\033[0;34m"
  CYAN="\033[0;36m"
  BOLD="\033[1m"
  RESET="\033[0m"
else
  RED=""; GREEN=""; YELLOW=""; BLUE=""; CYAN=""; BOLD=""; RESET=""
fi

info()    { printf "${CYAN}%s${RESET}\n" "$*"; }
ok()      { printf "${GREEN}%s${RESET}\n" "$*"; }
warn()    { printf "${YELLOW}%s${RESET}\n" "$*"; }
error()   { printf "${RED}%s${RESET}\n" "$*"; }
section() { printf "\n${BOLD}${BLUE}==> %s${RESET}\n" "$*"; }

# --- HELP / USAGE ---
show_help() {
  cat <<EOF
dump_src.sh - Create a clean source archive using git ls-files + ignore list

USAGE:
  ./dump_src.sh
  ./dump_src.sh --dry-run
  ./dump_src.sh --help

OPTIONS:
  --help, -h
        Shows this help text.

  --dry-run
        Shows what would be archived, but does NOT create an archive.

CONFIG FILE (dump_src.cfg):
  This file is optional and may contain three variables:

  1) archive_basename="project_name"
     Overrides the default archive base directory (project folder name).
     Also accepted as "basename" for backwards compatibility.

  2) file_list=()
     List of files NOT tracked in git that should still be included.
     Paths are relative to the project root.

     Example:
       file_list=(
         local_config.yaml
         scripts/generate_report.py
       )

  3) ignore_list=()
     Regex patterns (bash [[ =~ ]] syntax) for files to exclude.
     Patterns match against git paths (relative paths).
     Empty patterns are skipped.

     Example:
       ignore_list=(
         '^build/'
         '^\\.idea/'
         '^out/'
         '.*\\.iml$'
       )

FULL EXAMPLE (dump_src.cfg):

  archive_basename="swekt"

  file_list=(
    swe_test.py
    local_settings.json
  )

  ignore_list=(
    '^dump_src\\.(sh|cfg)$'
    '^build/'
    '^\\.idea/'
    '\\.iml$'
  )

NOTES:
  - git ls-files determines which files are included by default.
  - ignore_list patterns use Bash regex matching.
  - All archived paths start with "\$archive_basename/..."
  - Extra files in file_list are added even if they are not in git.

EOF
}

# Handle command-line options
dry_run=false
if [[ $# -gt 0 ]]; then
  case "$1" in
    --help|-h|help)
      show_help
      exit 0
      ;;
    --dry-run)
      dry_run=true
      ;;
    *)
      error "Unknown argument: $1"
      echo "Use --help for usage."
      exit 1
      ;;
  esac
fi

# --- Resolve script directory ---
SCRIPT_DIR="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$SCRIPT_DIR"

project="$(command basename "$SCRIPT_DIR")"
archive_basename="$project"

file_list=()
ignore_list=()

# --- Load optional config ---
if [[ -f dump_src.cfg ]]; then
  section "Loading configuration"
  # shellcheck disable=SC1091
  source dump_src.cfg
  # Backwards compatibility: accept legacy "basename" variable name
  if [[ -n "${basename:-}" ]]; then
    archive_basename="$basename"
  fi
fi

# --- Ensure git repo ---
section "Checking repository"
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  error "Not inside a git repository: $SCRIPT_DIR"
  exit 1
fi
ok "OK - inside git repository."

# --- ignore helper ---
is_ignored() {
  local fname="$1"
  local pat
  for pat in ${ignore_list[@]+"${ignore_list[@]}"}; do
    [[ -z "$pat" ]] && continue
    if [[ "$fname" =~ $pat ]]; then
      return 0
    fi
  done
  return 1
}

# Stats
git_files_count=0
extra_requested_count=0
extra_found_count=0
extra_missing_count=0
ignored_count=0
archived_count=0

ignored_files=()
extra_files_found=()
extra_files_missing=()

# ------------------------------------------------------------------------------
# 1. Collect git files
# ------------------------------------------------------------------------------
section "Collecting git files"
mapfile -t git_files < <(git ls-files)
git_files_count="${#git_files[@]}"
info "Found ${git_files_count} tracked git files."

# ------------------------------------------------------------------------------
# 2. Collect extra files
# ------------------------------------------------------------------------------
section "Collecting extra files"
extra_files=()
for f in ${file_list[@]+"${file_list[@]}"}; do
  extra_requested_count=$((extra_requested_count + 1))

  if [[ -f "$SCRIPT_DIR/$f" ]]; then
    extra_files+=("$f")
    extra_files_found+=("$f")
    extra_found_count=$((extra_found_count + 1))
  else
    extra_files_missing+=("$f")
    extra_missing_count=$((extra_missing_count + 1))
  fi
done

# ------------------------------------------------------------------------------
# 3. Filter + deduplicate
# ------------------------------------------------------------------------------
section "Filtering files"
declare -A seen
all_files=()

# git files
for f in "${git_files[@]}"; do
  [[ -z "$f" ]] && continue
  [[ ! -f "$f" ]] && continue

  if is_ignored "$f"; then
    ignored_files+=("$f")
    ignored_count=$((ignored_count + 1))
    continue
  fi

  all_files+=("$f")
  seen["$f"]=1
done

# extra files
for f in ${extra_files[@]+"${extra_files[@]}"}; do
  if is_ignored "$f"; then
    ignored_files+=("$f")
    ignored_count=$((ignored_count + 1))
    continue
  fi

  if [[ -z "${seen[$f]+x}" ]]; then
    all_files+=("$f")
    seen["$f"]=1
  fi
done

if [[ "${#all_files[@]}" -eq 0 ]]; then
  error "No files left to archive after filtering!"
  exit 1
fi

mapfile -t all_files_sorted < <(printf '%s\n' "${all_files[@]}" | sort)
archived_count="${#all_files_sorted[@]}"
ok "Using ${archived_count} files."

# ------------------------------------------------------------------------------
# 4. Build file list for tar
# ------------------------------------------------------------------------------
section "Preparing file list"

tmpfile="$(mktemp "${TMPDIR:-/tmp}/dump_src.XXXXXX")"
trap 'rm -f "$tmpfile"' EXIT

for f in "${all_files_sorted[@]}"; do
  printf '%s\n' "$f" >> "$tmpfile"
done

# ------------------------------------------------------------------------------
# 5. DRY-RUN MODE
# ------------------------------------------------------------------------------
if [[ "$dry_run" == true ]]; then
  warn "DRY RUN - NO ARCHIVE CREATED!"
  section "Files that *would* be archived:"
  for f in "${all_files_sorted[@]}"; do
    echo "  $f"
  done

  section "Summary"
  echo "Archived files total: $archived_count"
  ok "Done (dry-run)."
  exit 0
fi

# ------------------------------------------------------------------------------
# 6. Create archive
# ------------------------------------------------------------------------------
section "Creating archive"

archive_path="$SCRIPT_DIR/$archive_basename.tar.bz2"

# Run tar from SCRIPT_DIR so paths in tmpfile resolve correctly,
# and rewrite all archived paths to live under "$archive_basename/".
tar -C "$SCRIPT_DIR" \
    --transform="s|^|$archive_basename/|" \
    -cjf "$archive_path" \
    --files-from="$tmpfile"

ok "Archive created: $archive_path"

# ------------------------------------------------------------------------------
# 7. Summary
# ------------------------------------------------------------------------------
section "Summary"
sha256="$(sha256sum "$archive_path" | awk '{print $1}')"
printf "project: %s\n" "$project"
printf "archive: %s\n" "$archive_basename.tar.bz2"
printf "sha256:  %s\n" "$sha256"
echo

printf "Tracked git files:       %d\n" "$git_files_count"
printf "Extra files requested:   %d\n" "$extra_requested_count"
printf "  -> found:              %d\n" "$extra_found_count"
printf "  -> missing:            %d\n" "$extra_missing_count"
printf "Ignored by patterns:     %d\n" "$ignored_count"
printf "Archived files total:    %d\n" "$archived_count"
echo

if (( extra_found_count > 0 )); then
  info "Extra files included from file_list:"
  for f in "${extra_files_found[@]}"; do
    printf "  - %s\n" "$f"
  done
  echo
fi

if (( extra_missing_count > 0 )); then
  warn "Missing extra files:"
  for f in "${extra_files_missing[@]}"; do
    printf "  - %s\n" "$f"
  done
  echo
fi

if (( ignored_count > 0 )); then
  info "Ignored files (by ignore_list):"
  for f in "${ignored_files[@]}"; do
    printf "  - %s\n" "$f"
  done
  echo
fi

ok "Done."
