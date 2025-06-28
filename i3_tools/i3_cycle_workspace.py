#!/usr/bin/env python3
#
# provides mod+tab functionality between workspaces, switching
# between n workspaces; example i3 conf:
#     exec_always --no-startup-id i3-cycle-workspace-daemon --focused-output --history 2
#     bindsym $mod+Tab exec --no-startup-id i3-cycle-workspace

import asyncio
import logging
from argparse import ArgumentParser

SOCKET_FILE = '/tmp/.i3-cycle-workspace.sock'
SWITCH_MSG = 'switch'.encode()


async def send_switch():
    reader, writer = await asyncio.open_unix_connection(SOCKET_FILE)

    logging.info('sending switch message')
    writer.write(SWITCH_MSG)
    await writer.drain()

    logging.info('closing the connection')
    writer.close()
    await writer.wait_closed()


def main():
    parser = ArgumentParser(prog='i3-cycle-workspace',
                            description="""
        Cycle backwards through the history of focused workspaces.
        This script should be launched from ~/.xsession or ~/.xinitrc.
        Use the `--history` option to set the maximum number of workspaces to be
        stored in the focus history (Default 16 workspaces).
        Use the `--delay` option to set the delay between focusing the
        selected workspace and updating the focus history (Default 2.0 seconds).
        Use a value of 0.0 seconds to toggle focus only between the current
        and the previously focused workspace.

        To trigger focus switching, execute the script from a keybinding with
        the `--switch` option, or send SIGUSR1 to the process.""")
    parser.add_argument('--debug', dest='debug', action='store_true', help='Turn on debug logging')
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)

    asyncio.run(send_switch())
