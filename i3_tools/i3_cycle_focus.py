#!/usr/bin/env python3
#
# provides alt+tab functionality between windows, switching
# between n windows; example i3 conf:
#     exec_always --no-startup-id i3-cycle-focus-daemon --history 2
#     bindsym $mod1+Tab exec --no-startup-id i3-cycle-focus.py
#
# similar to i3-focus-last-window.sh
# from https://github.com/acrisci/i3ipc-python/

import asyncio
import logging
from argparse import ArgumentParser

SOCKET_FILE = '/tmp/.i3-cycle-focus.sock'
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
    parser = ArgumentParser(prog='i3-cycle-focus',
                            description="""
        Cycle backwards through the history of focused windows (aka Alt-Tab).
        This script should be launched from ~/.xsession or ~/.xinitrc.
        Use the `--history` option to set the maximum number of windows to be
        stored in the focus history (Default 16 windows).
        Use the `--delay` option to set the delay between focusing the
        selected window and updating the focus history (Default 2.0 seconds).
        Use a value of 0.0 seconds to toggle focus only between the current
        and the previously focused window. Use the `--ignore-floating` option
        to exclude all floating windows when cycling and updating the focus
        history. Use the `--visible-workspaces` option to include windows on
        visible workspaces only when cycling the focus history. Use the
        `--active-workspace` option to include windows on the active workspace
        only when cycling the focus history.

        To trigger focus switching, execute the script from a keybinding with
        the `--switch` option, or send SIGUSR1 to the process.""")
    parser.add_argument('--debug', dest='debug', action='store_true', help='Turn on debug logging')
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)

    asyncio.run(send_switch())
