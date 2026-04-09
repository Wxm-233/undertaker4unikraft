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

import os
import re

import kbuildparse.base_classes as BaseClasses
import kbuildparse.data_structures as DataStructures
import kbuildparse.linux.linux as Linux


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


class _02_UnikraftObjects(Linux._02_LinuxObjects):
    """Object handling for Unikraft makefiles."""

    obj_line = r"\s*(obj|lib|core|plat|arch)-(y|m|\$[\(\{]" + \
               Linux.CONFIG_FORMAT + r"[\)\}])\s*(:=|\+=|=)\s*(([A-Za-z0-9.,_\$\(\)/-]+\s*)+)"
    regex_obj = re.compile(obj_line)

    def __init__(self, model, arch):
        super(_02_UnikraftObjects, self).__init__(model, arch)


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
