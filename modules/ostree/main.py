#
# This file is part of Liri.
#
# Copyright (C) 2019 Pier Luigi Fiorini <pierluigi.fiorini@gmail.com>
#
# $BEGIN_LICENSE:GPL3+$
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
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# $END_LICENSE$
#

import json
import subprocess
import libcalamares
import os

def mkdir_p(path):
    """
    Creates all subdirectories leading to the path.

    :param path: Path
    """
    if not os.path.exists(path):
        os.makedirs(path)


def bind_mount(src, dest=None, bind_ro=False, recurse=True):
    """
    Bind mount source to destination.

    :param src: Source path
    :param dest: Destination path
    :param bind_ro: Mount read-only
    :param recurse: Use --rbind to recurse, otherwise plain --bind
    """

    if libcalamares.globalstorage.contains('extraMounts'):
        extra_mounts = libcalamares.globalstorage.value('extraMounts')
    else:
        extra_mounts = []

    # Same basename by default
    if dest is None:
        dest = src

    # Make sure the mount point is created
    mkdir_p(dest)

    # Determine bind argument
    if bind_ro:
        subprocess.check_call(['mount', '--bind', src, src])
        subprocess.check_call(['mount', '--bind', '-o', 'remount,ro', src, src])
    else:
        if recurse:
            bindopt = '--rbind'
        else:
            bindopt = '--bind'
        subprocess.check_call(['mount', bindopt, src, dest])

    entry = {'device': src, 'mountPoint': dest}
    if bind_ro or not recurse:
        entry['options'] = 'bind'
    extra_mounts.append(entry)
    libcalamares.globalstorage.insert('extraMounts', extra_mounts)


def run():
    """
    Install the OS tree on the root file system.
    """

    # Installation path
    install_path = libcalamares.globalstorage.value('rootMountPoint')
    if not install_path:
        return ("No mount point for root partition in globalstorage",
                "globalstorage does not contain a \"rootMountPoint\" key, "
                "doing nothing")
    if not os.path.exists(install_path):
        return (f"Bad mount point for root partition in globalstorage",
                 "globalstorage[\"rootMountPoint\"] is \"{install_path}\", which does not "
                 "exist, doing nothing")

    # Partitions
    partitions = libcalamares.globalstorage.value('partitions')

    # OSTree /var
    varroot = install_path + '/ostree/deploy/lirios/var'

    # If the user wants /var into a separate partition, we need to make OSTree
    # put those files there during installation
    has_var_mountpoint = False
    for partition in partitions:
        if partition['mountPoint'] == '/var':
            has_var_mountpoint = True
            bind_mount(install_path + '/var', varroot, recurse=False)
            break

    progname = '/usr/bin/calamares-ostree-install'

    # The Calamares Python interpreter freezes when loading gobject-introspection, so we moved the
    # code to an external process

    deployment_path = None

    with subprocess.Popen([progname, install_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as p:
        (stdout, stderr) = p.communicate()

        if p.returncode == 0:
            output = stdout.decode('utf-8')
            for line in output.split('\n'):
                if line.startswith('PROGRESS'):
                    percent = float(line[9:])
                    libcalamares.job.setprogress(percent)
                elif line.startswith('RESULT'):
                    deployment_path = line[7:]
                    libcalamares.globalstorage.insert('ostreeDeploymentPath', deployment_path)
                else:
                    libcalamares.utils.debug(line)
        else:
            return json.loads(stderr.decode('utf-8'))

    if deployment_path is None:
        return ('No deployment path', 'Unable to find OS tree deployment.')

    # If /var is on the root file system we want to bind mount it to /var
    # so that chroot will be able to see it
    if has_var_mountpoint is False:
        bind_mount(varroot, dest=install_path + '/var', recurse=False)

    # Bind mount deployment into installation path for chroot
    bind_mount(deployment_path, install_path)

    # Run tmpfiles to make subdirectories of /var
    subprocess.run(['systemd-tmpfiles', '--create', '--boot',
                    '--root=' + install_path], check=False)

    # Reverse extra mounts
    extra_mounts = libcalamares.globalstorage.value('extraMounts')
    extra_mounts.reverse()
    libcalamares.globalstorage.insert('extraMounts', extra_mounts)

    # Print extra mounts for debugging
    for mount in libcalamares.globalstorage.value('extraMounts'):
        libcalamares.utils.debug(f'Extra mount point: {mount}')

    return None
