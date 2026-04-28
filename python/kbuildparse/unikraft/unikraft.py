"""Implementation of kbuildparse base classes for Unikraft."""

# Copyright (C) 2026 GitHub Copilot
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import logging
import os
import re

import kbuildparse.base_classes as BaseClasses
import kbuildparse.data_structures as DataStructures
import kbuildparse.linux.linux as Linux


def _regex_else_match_unikraft(line, ifdef_condition, global_vars):
    """Unikraft variant of else handling that tolerates unmatched else."""
    regex_match = Linux.REGEX_ELSE.match(line)
    if not regex_match:
        return False

    if global_vars["no_config_nesting"] > 0:
        return True

    if len(ifdef_condition) == 0:
        logging.debug("Ignoring unmatched else in Unikraft makefile")
        return True

    last = ifdef_condition.pop()
    if last.startswith("!"):
        ifdef_condition.add_condition(last[1:])
    else:
        ifdef_condition.add_condition("!" + last)
    return True


def _regex_endif_match_unikraft(line, ifdef_condition, global_vars):
    """Unikraft variant of endif handling that tolerates unmatched endif."""
    regex_match = Linux.REGEX_ENDIF.match(line)
    if not regex_match:
        return False

    if global_vars["no_config_nesting"] > 0:
        global_vars.decrement_variable("no_config_nesting")
        return True

    if len(ifdef_condition) == 0:
        logging.debug("Ignoring unmatched endif in Unikraft makefile")
        return True

    ifdef_condition.pop()
    return True


def _update_if_condition_unikraft(line, ifdef_condition, global_vars, local_vars, model):
    """Update the condition stack while being tolerant to malformed nesting."""
    if Linux.regex_ifneq_match(line, ifdef_condition, global_vars, model) or \
            Linux.regex_ifndef_match(line, ifdef_condition, global_vars, model) or \
            _regex_else_match_unikraft(line, ifdef_condition, global_vars) or \
            _regex_endif_match_unikraft(line, ifdef_condition, global_vars):
        return True
    return global_vars["no_config_nesting"] > 0


class UnikraftInit(Linux.LinuxInit):
    """Init class for Unikraft."""

    def __init__(self, model, arch):
        super(UnikraftInit, self).__init__(model, arch)

    def get_file_for_subdirectory(self, directory):
        """Select the correct Kbuild-like makefile in a directory."""
        if not directory.endswith('/'):
            directory += '/'

        for candidate in ("Makefile.uk", "Makefile", "Kbuild", "Config.uk"):
            descend = directory + candidate
            if os.path.isfile(descend):
                return descend

        return directory + "Makefile.uk"

    def process(self, parser, args, dirs_to_process):
        """Initialize the directories that should be parsed for Unikraft."""
        parser.global_vars.create_variable("no_config_nesting", 0)

        if len(args.directory) > 0:
            for item in args.directory:
                dirs_to_process[item] = DataStructures.Precondition()
        else:
            for subdir in ["arch/", "core/", "drivers/", "lib/", "plat/", "support/"]:
                if os.path.isdir(subdir):
                    dirs_to_process[subdir] = DataStructures.Precondition()

        for candidate in (
            "arch/%s/Makefile.uk" % args.arch,
            "arch/%s/Makefile" % args.arch,
            "plat/%s/Makefile.uk" % args.arch,
            "plat/%s/Makefile" % args.arch,
        ):
            if os.path.isfile(candidate):
                self.parse_architecture_path(candidate, dirs_to_process)
                break


class UnikraftBefore(Linux.LinuxBefore):
    """Initialization of per-file variables for Unikraft."""

    def __init__(self, model, arch):
        super(UnikraftBefore, self).__init__(model, arch)


class _00_UnikraftDefinitions(Linux._00_LinuxDefinitions):
    """Definition handling for Unikraft makefiles."""

    def __init__(self, model, arch):
        super(_00_UnikraftDefinitions, self).__init__(model, arch)


class _01_UnikraftIf(Linux._01_LinuxIf):
    """Conditional handling for Unikraft makefiles."""

    def __init__(self, model, arch):
        super(_01_UnikraftIf, self).__init__(model, arch)

    def process(self, parser, line, basepath):
        _line = line.processed_line
        retval = _update_if_condition_unikraft(
            _line,
            parser.local_vars["ifdef_condition"],
            parser.global_vars,
            parser.local_vars,
            self.model,
        )
        line.condition = parser.local_vars["ifdef_condition"][:]
        line.invalid = retval
        return retval


class _02_UnikraftObjects(Linux._02_LinuxObjects):
    """Object handling for Unikraft makefiles."""

    obj_line = r"\s*(obj|lib|core|plat|arch)-(y|m|\$[\(\{]" + \
               Linux.CONFIG_FORMAT + r"[\)\}])\s*(:=|\+=|=)\s*(([A-Za-z0-9.,_\$\(\)/-]+\s*)+)"
    regex_obj = re.compile(obj_line)

    def __init__(self, model, arch):
        super(_02_UnikraftObjects, self).__init__(model, arch)


class _02_UnikraftLibrarySrcs(BaseClasses.DuringPass):
    """Extract source files from LIBXXX_SRCS-y and LIBXXX_SRCS-$(CONFIG_*) patterns."""

    # Pattern: LIBXXX_SRCS-y += file.c or LIBXXX_SRCS-$(CONFIG_FOO) += file.c
    lib_srcs_line = r"\s*(\w+)_SRCS-([y|m]|\$[\(\{]" + Linux.CONFIG_FORMAT + r"[\)\}])\s*(:=|\+=|=)\s*(.+)"
    regex_lib_srcs = re.compile(lib_srcs_line)

    def __init__(self, model, arch):
        super(_02_UnikraftLibrarySrcs, self).__init__(model, arch)

    def process(self, parser, line, basepath):
        _line = line.processed_line
        if not _line or _line.startswith("#"):
            return False

        match = self.regex_lib_srcs.match(_line)
        if not match:
            return False

        lib_prefix = match.group(1)  # e.g., "LIBUKALLOC"
        condition_str = match.group(2)  # e.g., "y" or "$(CONFIG_X)"
        files_str = match.group(4)  # e.g., "$(LIBUKALLOC_BASE)/alloc.c $(LIBUKALLOC_BASE)/stats.c"

        # Determine the actual condition
        if condition_str == "y":
            condition = DataStructures.Precondition()
        elif condition_str == "m":
            condition = DataStructures.Precondition()
            condition.add_condition("MODULE")
        else:
            # Extract CONFIG variable from $(CONFIG_XXX)
            config_match = re.search(r'\$[\(\{](' + Linux.CONFIG_FORMAT + r')[\)\}]', condition_str)
            if config_match:
                config_var = config_match.group(1)
                condition = DataStructures.Precondition()
                condition.add_condition(config_var)
            else:
                return False

        # Parse file list (handle $(VAR) expansions)
        files = re.findall(r'[\$\w\.\-/(){}]+', files_str)
        for file_path in files:
            file_path = file_path.strip()
            if not file_path:
                continue

            # Try to expand $(VAR) references
            # Common patterns: $(LIBXXX_BASE), $(ARCH_BASE), etc.
            if '$(LIBNAME_BASE)' in file_path:
                # This is a generic placeholder, need proper resolution
                continue
            elif '$(' in file_path:
                # Try to substitute from parser.local_vars
                var_name = re.search(r'\$\((\w+)\)', file_path)
                if var_name:
                    var = var_name.group(1)
                    if var in parser.local_vars:
                        file_path = file_path.replace('$(' + var + ')', parser.local_vars[var])
                    elif var in parser.global_vars:
                        file_path = file_path.replace('$(' + var + ')', parser.global_vars[var])

            # Add source object to the model
            if file_path and (file_path.endswith('.c') or file_path.endswith('.ld')):
                # Normalize path (remove leading ./)
                if file_path.startswith('./'):
                    file_path = file_path[2:]

                # Create a combined condition: library enable AND file condition
                combined_condition = DataStructures.Precondition()
                # Assume library is gated by CONFIG_LIB* which will be resolved later
                combined_condition.add_condition(condition)

                # Store the file association
                if hasattr(self, 'file_conditions'):
                    if file_path not in self.file_conditions:
                        self.file_conditions[file_path] = []
                    self.file_conditions[file_path].append(combined_condition)
                else:
                    self.file_conditions = {file_path: [combined_condition]}

                logging.debug(
                    "Unikraft source: LIB=%s FILE=%s CONDITION=%s",
                    lib_prefix, file_path, condition
                )

        line.invalid = False
        return True


class _01_UnikraftExpandMacros(Linux._01_LinuxExpandMacros):
    """Macro expansion stage for Unikraft makefiles."""

    def __init__(self, model, arch):
        super(_01_UnikraftExpandMacros, self).__init__(model, arch)


class _02_UnikraftProcessSubdirectories(Linux._02_LinuxProcessSubdirectories):
    """Subdirectory descent stage for Unikraft makefiles."""

    def __init__(self, model, arch):
        super(_02_UnikraftProcessSubdirectories, self).__init__(model, arch)


class _03_UnikraftOutput(Linux._03_LinuxOutput):
    """Final output stage for Unikraft makefiles."""

    def __init__(self, model, arch):
        super(_03_UnikraftOutput, self).__init__(model, arch)


class UnikraftAfter(_03_UnikraftOutput):
    """Backward-compatible alias for output stage."""

    def __init__(self, model, arch):
        super(UnikraftAfter, self).__init__(model, arch)
