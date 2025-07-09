#!/usr/bin/env python3
#
# provides mod+tab functionality between workspaces, switching
# between n workspaces; example i3 conf:
#     exec_always --no-startup-id i3-cycle-workspace --focused-output --history 2
#     bindsym $mod+Tab exec --no-startup-id killall -s SIGUSR1 i3-cycle-workspace

from argparse import ArgumentParser
from i3ipc.aio import Connection
import asyncio
import signal
import os
import json
import logging

STATE_FILE = '/tmp/.i3-cycle-workspace.state'
STATE_VER = 1  # bump this whenever persisted state data structure changes
WS_HISTORY = 16
UPDATE_DELAY = 2.0

SWITCH_MSG = 'switch'.encode()
GLOBAL_KEY = '_global_'  # for when we're tracking workspaces globally, not per output


class FocusWatcher:
    def __init__(self):
        self.i3 = None
        self.update_task = None
        self.ws_list = {}
        self.ws_index = {}

    def hydrate_state(self) -> None:
        if os.path.isfile(STATE_FILE) and os.access(STATE_FILE, os.R_OK):
            with open(STATE_FILE, 'r') as f:
                try:
                    state = json.load(f)
                except Exception:
                    return

            if type(state) == dict and state.get('ver') == STATE_VER:
                self.ws_list = state.get('ws_list') or {}
                self.ws_index = state.get('ws_index') or {}

    def persist_state(self) -> None:
        data = {
            'ws_list': self.ws_list,
            'ws_index': self.ws_index,
            'ver': STATE_VER
        }

        with open(STATE_FILE, 'w') as f:
            f.write(json.dumps(
                    data,
                    indent=4,
                    sort_keys=True,
                    separators=(',', ': '),
                    ensure_ascii=False))

    def on_shutdown(self, i3conn, e):
        try:
            if e.change == 'restart':
                self.persist_state()
        finally:
            os._exit(0)

    async def on_ws_focus(self, i3conn, event):
        logging.info('got workspace focus event')
        if self.update_task is not None:
            self.update_task.cancel()

        logging.info('scheduling task to update ws list')
        self.update_task = asyncio.create_task(self.update_ws_list(event.current))  # 'old' attr refers to previous ws, if applicable

    async def connect(self):
        self.i3 = await Connection().connect()
        self.i3.on('workspace::focus', self.on_ws_focus)
        self.i3.on('shutdown', self.on_shutdown)

    async def update_ws_list(self, container):
        if UPDATE_DELAY != 0.0:
            await asyncio.sleep(UPDATE_DELAY)

        logging.info('updating ws list')

        key = container.ipc_data['output'] if args.focused_output else GLOBAL_KEY
        wslist = self.ws_list.get(key)
        if wslist is None:
            wslist = self.ws_list[key] = []
            self.ws_index[key] = [1]
        else:
            self.ws_index[key][0] = 1

        ws_id = container.name
        if ws_id in wslist:
            wslist.remove(ws_id)

        wslist.insert(0, ws_id)

        if len(wslist) > MAX_WS_HISTORY:
            del wslist[MAX_WS_HISTORY:]

        logging.info('new ws list: {}'.format(wslist))

    def get_valid_workspaces(self, tree, config_key):
        if args.focused_output:
            return [ws.name for ws in tree.workspaces() if ws.ipc_data['output'] == config_key]
        else:
            return [ws.name for ws in tree.workspaces()]

    async def switch_ws(self):
        logging.info('switching ws')
        tree = await self.i3.get_tree()
        focused_ws = tree.find_focused().workspace()
        key = (focused_ws.ipc_data['output'] if
                args.focused_output else GLOBAL_KEY)

        wslist = self.ws_list.get(key)
        if wslist is None:
            return
        wsidx = self.ws_index.get(key)

        workspaces = self.get_valid_workspaces(tree, key)
        logging.info('valid workspaces = {}'.format(workspaces))

        for ws_id in wslist[wsidx[0]:]:
            if ws_id not in workspaces:
                wslist.remove(ws_id)
            elif ws_id == focused_ws.name:
                wsidx[0] += 1
            else:
                if wsidx[0] < min(len(wslist), WS_HISTORY) - 1:
                    wsidx[0] += 1
                else:
                    wsidx[0] = 0
                logging.info('focusing ws name={}'.format(ws_id))
                await self.i3.command('workspace {}'.format(ws_id))
                break


async def run_server(loop):
    focus_watcher = FocusWatcher()
    focus_watcher.hydrate_state()
    await focus_watcher.connect()
    loop.add_signal_handler(signal.SIGUSR1, lambda: loop.create_task(focus_watcher.switch_ws()))


def main():
    global WS_HISTORY
    global MAX_WS_HISTORY
    global UPDATE_DELAY
    global args

    parser = ArgumentParser(prog='i3-cycle-workspace-daemon',
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
    mutex_group = parser.add_mutually_exclusive_group()

    parser.add_argument('--history',
                        dest='history',
                        help='Maximum number of workspaces in the focus history',
                        type=int)
    parser.add_argument('--delay',
                        dest='delay',
                        help='Delay before updating workspace history',
                        type=float)
    mutex_group.add_argument('--focused-output',
                        dest='focused_output',
                        action='store_true',
                        help='Include workspaces on the '
                        'focused output/screen only when cycling the focus history')
    mutex_group.add_argument('--switch',
                        dest='switch',
                        action='store_true',
                        help='Switch to the previous workspace',
                        default=False)
    parser.add_argument('--debug', dest='debug', action='store_true', help='Turn on debug logging')
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)

    if args.history:
        WS_HISTORY = args.history

    MAX_WS_HISTORY = WS_HISTORY + 5

    if (args.delay and args.delay > 0) or args.delay == 0.0:
        UPDATE_DELAY = args.delay

    loop = asyncio.get_event_loop()
    loop.create_task(run_server(loop))
    loop.run_forever()
