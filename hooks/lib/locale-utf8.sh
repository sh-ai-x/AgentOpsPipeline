#!/usr/bin/env bash
# locale-utf8.sh — force a UTF-8 locale for grep -E with multi-byte patterns.
#
# Source this from any hook that runs grep against user-visible content
# with potential multi-byte characters (Korean, em-dash, etc.). CI runners
# often default to POSIX/C locale which makes grep -E reject multi-byte
# patterns with "Invalid collation character" and silently emit zero matches.
#
# Detection priority:
#   1. Honour the caller's explicit LC_ALL/LANG if they already point at UTF-8.
#   2. C.UTF-8 if installed (always present on glibc >= 2.13).
#   3. en_US.UTF-8 if installed (default on macOS).
#   4. Print a one-shot WARN to stderr; caller decides whether to skip
#      pattern matching or fall back to a different scheme.
#
# Sourced; not executed. Bail if executed directly.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  printf 'locale-utf8.sh must be sourced, not executed.\n' >&2
  exit 1
fi

_existing_utf=0
case "${LC_ALL:-}${LANG:-}" in *.[Uu][Tt][Ff]-?8*) _existing_utf=1 ;; esac
if [ "$_existing_utf" = "1" ]; then
  : # caller already set a UTF-8 locale; trust it
elif _LOCALES="$(locale -a 2>/dev/null || true)" \
     && printf '%s\n' "$_LOCALES" | grep -qiE '^C\.[Uu][Tt][Ff]-?8$'; then
  export LC_ALL=C.UTF-8 LANG=C.UTF-8
elif printf '%s\n' "$_LOCALES" | grep -qiE '^en_US\.[Uu][Tt][Ff]-?8$'; then
  export LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
else
  printf '[locale-utf8] WARN: no UTF-8 locale found in locale -a; multi-byte pattern matching disabled. Currently: LC_ALL=%s LANG=%s.\n' "${LC_ALL:-unset}" "${LANG:-unset}" >&2
fi
unset _LOCALES _existing_utf 2>/dev/null || true
