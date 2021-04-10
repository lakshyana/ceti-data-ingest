#!/usr/bin/python3

# This script is assumed to be running on a linux x86 computer
# while being attached to the same wireless network as a charged and
# running whale tag to pull the data from.

# All of the data will be pulled into the the forlder ./data
# Whale tags are embedded computers that automatically connect to a "ceti"
# wireless network. They also support Ethernet over USB protocol, but
# the phisical access to the USB port may be difficult to reach.

# Each whale tag has a a unique hostname of the format "wt-XXXXXXXXXXXX",
# where X are alphanumerics.

# To access a whale tag, connect using ssh on port 22.
# The username is "pi", the password is "ceticeti".

import argparse
import asyncio
import findssh
import hashlib
import os
import paramiko
import re
import socket
import sys

LOCAL_DATA_PATH = os.path.join(os.getcwd(), "data")
DEFAULT_USERNAME = "pi"
DEFAULT_PASSWORD = "ceticeti"


# Scan the active LAN for servers with open ssh on port 22
def find_ssh_servers():
    netspec = findssh.netfromaddress(findssh.getLANip())
    coro = findssh.get_hosts(netspec, 22, "ssh", 1.0)
    sys.stdout = open(os.devnull, "w")
    hosts = asyncio.run(coro)
    sys.stdout = sys.__stdout__
    return hosts


# get hostnames for all ssh servers
def get_hostnames_by_addr(addrs):
    hostnames = []
    for a in addrs:
        addr = str(a[0])
        hname = socket.gethostbyaddr(addr)[0]
        hname = hname.split(".")[0]
        hostnames.append(hname)
    return hostnames


def can_connect(hostname):
    try:
        # test connecting with ssh using default tag password
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname,
            username=DEFAULT_USERNAME,
            password=DEFAULT_PASSWORD)
        ssh.close()
    except BaseException:
        return False
    return True


# Perform local discovery of the tags and return the list of them
def tag_hostnames(hostnames):
    hnames = []
    for hname in hostnames:
        if re.match("wt-[a-z0-9]{12}", hname):
            if (can_connect(hname)):
                hnames.append(hname)
    return hnames


# Get sha256 digest of the local file
def sha256sum(file_path):
    h = hashlib.sha256()
    with open(file_path, 'rb') as file:
        while True:
            chunk = file.read(h.block_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# Prepare the list of files on the remote whale tag that are missing
# from the local data folder
def create_filelist_to_download(hostname):
    files_to_download = []
    try:
        # Connect to the remote whale tag
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname,
            username=DEFAULT_USERNAME,
            password=DEFAULT_PASSWORD)

        # Prepare the local storage to accept the files
        local_data_folder = os.path.join(LOCAL_DATA_PATH, hostname)
        if not os.path.exists(local_data_folder):
            os.makedirs(local_data_folder)
        local_files = os.listdir(local_data_folder)

        # Check what files are available for download from the tag
        remote_data_folder = os.path.join("/data", hostname)
        _, stdout, _ = ssh.exec_command("ls " + remote_data_folder)
        remote_files = stdout.readlines()

        # Create the list of files to download
        for fname in remote_files:
            fname = fname.strip()
            if (fname not in local_files):
                files_to_download.append(
                    os.path.join(remote_data_folder, fname))
                continue

            # Here: the file with this name is already present.
            # Compare its hash to the local file.
            # If different, lets re-download that file again.
            local_sha = sha256sum(os.path.join(local_data_folder, fname))
            _, stdout, _ = ssh.exec_command(
                "sha256sum " + os.path.join(remote_data_folder, fname))
            remote_sha = stdout.read().decode("utf-8").split(" ")[0]

            if (local_sha != remote_sha):
                files_to_download.append(
                    os.path.join(remote_data_folder, fname))

    finally:
        ssh.close()
    return files_to_download

# Find all of the whale tags available on the local LAN


def list_whale_tags_online():
    servers = find_ssh_servers()
    hostnames = get_hostnames_by_addr(servers)
    tags = tag_hostnames(hostnames)
    return tags

# Download a file over sftp


def download_remote_file(hostname, remote_file):
    local_file = os.path.join(LOCAL_DATA_PATH, hostname)
    local_file = os.path.join(local_file, os.path.basename(remote_file))
    try:
        print("Downloading " + remote_file)
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname,
            username=DEFAULT_USERNAME,
            password=DEFAULT_PASSWORD)
        sftp = ssh.open_sftp()
        sftp.get(remote_file, local_file)
    finally:
        sftp.close()
        ssh.close()


def download_all(hostname):
    if not can_connect(hostname):
        print("Could not connect to host: " + str(hostname))
        return
    print("Connecting to " + hostname)
    filelist = create_filelist_to_download(hostname)
    for filename in filelist:
        download_remote_file(hostname, filename)
    print("Done downloading")


# CAREFUL: ERASES ALL DATA FROM WHALE TAG
def clean_tag(hostname):
    if not can_connect(hostname):
        print("Could not connect to host: " + str(hostname))
        return
    filelist = create_filelist_to_download(hostname)
    if filelist:
        print("Not all data have been downloaded from this tag. Quitting...")
        return
    print("Erasing all collected data from whale tag " + hostname)
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname,
            username=DEFAULT_USERNAME,
            password=DEFAULT_PASSWORD)
        ssh.exec_command("rm -rf " + os.path.join("/data", hostname, "*"))
    finally:
        ssh.close()


def main():
    p = argparse.ArgumentParser(
        "Discover whale tags on LAN and download data off them")
    p.add_argument(
        "-l",
        "--list",
        help="List available whale tags",
        action="store_true")
    p.add_argument(
        "-t",
        "--tag",
        help="Download data from specific tag (by hostname)")
    p.add_argument(
        "-a",
        "--all",
        help="Download all data from all whale tags",
        action="store_true")
    p.add_argument(
        "-ct",
        "--clean_tag",
        help="Removes all collected data from a whale tag (by hostname)")
    p.add_argument(
        "-ca",
        "--clean_all_tags",
        help="Removes all collected data from all accessible tags",
        action="store_true")

    if len(sys.argv) == 1:
        p.print_help(sys.stderr)
        sys.exit(1)

    P = p.parse_args()

    if P.list:
        tag_list = list_whale_tags_online()
        for tag in tag_list:
            print(tag)

    if P.tag:
        download_all(P.tag.strip())

    if P.all:
        print("Searching for whale tags on LAN")
        tag_list = list_whale_tags_online()
        print("Found: " + str(tag_list))
        for tag in tag_list:
            download_all(tag)

    if P.clean_tag:
        clean_tag(P.clean_tag.strip())

    if P.clean_all_tags:
        print("Searching for whale tags on LAN")
        tag_list = list_whale_tags_online()
        print("Found: " + str(tag_list))
        for tag in tag_list:
            clean_tag(tag)


if __name__ == "__main__":
    main()
