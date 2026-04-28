#!/usr/bin/env python3
import re

# Test the regex directly
lib_srcs_pattern = re.compile(
    r'^\s*(\w+)_SRCS-([ym]|\$\(CONFIG_\w+\)|\$\{CONFIG_\w+\})\s*[:+]?=\s*(.+)$',
    re.MULTILINE
)

test_lines = [
    "LIBUKALLOC_SRCS-y += $(LIBUKALLOC_BASE)/alloc.c",
    "LIBUKALLOC_SRCS-$(CONFIG_LIBUKALLOC_IFSTATS) += $(LIBUKALLOC_BASE)/stats.c",
]

for line in test_lines:
    match = lib_srcs_pattern.search(line)
    if match:
        print(f"MATCHED: {line}")
        print(f"  Groups: {match.groups()}")
    else:
        print(f"NO MATCH: {line}")
