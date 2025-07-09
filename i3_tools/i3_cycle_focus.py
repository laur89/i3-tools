#!/usr/bin/env python3
#
# provides alt+tab functionality between windows, switching
# between n windows; example i3 conf:
#     exec_always --no-startup-id i3-cycle-focus --history 2
#     bindsym $mod1+Tab exec --no-startup-id killall -s SIGUSR1 i3-cycle-focus
#
# similar to i3-focus-last-window.sh
# from https://github.com/acrisci/i3ipc-python/

from argparse import ArgumentParser
from i3ipc.aio import Connection
import asyncio
import signal
import os
import json
import logging

STATE_FILE = '/tmp/.i3-cycle-focus.state'
STATE_VER = 1  # bump this whenever persisted state data structure changes
WIN_HISTORY = 16
UPDATE_DELAY = 2.0

SWITCH_MSG = 'switch'.encode()
GLOBAL_KEY = '_global_'  # for when we're tracking windows globally, not per output/ws


class FocusWatcher:
    def __init__(self):
        self.i3 = None
        self.update_task = None
        self.window_list = {}
        self.window_index = {}

    def hydrate_state(self) -> None:
        if os.path.isfile(STATE_FILE) and os.access(STATE_FILE, os.R_OK):
            with open(STATE_FILE, 'r') as f:
                try:
                    state = json.load(f)
                except Exception:
                    return

            if type(state) == dict and state.get('ver') == STATE_VER:
                self.window_list = state.get('window_list') or {}
                self.window_index = state.get('window_index') or {}

    def persist_state(self) -> None:
        data = {
            'window_list': self.window_list,
            'window_index': self.window_index,
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

    async def connect(self):
        self.i3 = await Connection().connect()
        self.i3.on('window::focus', self.on_window_focus)
        self.i3.on('shutdown', self.on_shutdown)

    async def update_window_list(self, container):
        if UPDATE_DELAY != 0.0:
            await asyncio.sleep(UPDATE_DELAY)

        logging.info('updating window list')

        key = GLOBAL_KEY
        if KEYED_CONF:
            key = (container.ipc_data['output'] if PER_OUTPUT
                   else str((await self.i3.get_tree()).find_focused().workspace().num))

        wlist = self.window_list.get(key)
        if wlist is None:
            wlist = self.window_list[key] = []
            self.window_index[key] = [1]
        else:
            self.window_index[key][0] = 1

        window_id = container.window
        if window_id in wlist:
            wlist.remove(window_id)

        wlist.insert(0, window_id)

        if len(wlist) > MAX_WIN_HISTORY:
            del wlist[MAX_WIN_HISTORY:]

        logging.info('new window list: {}'.format(wlist))

    async def get_valid_windows(self, tree, focused_ws):
        if args.active_workspace or args.focused_workspace:
            return set(w.window for w in focused_ws.leaves())
        elif args.visible_workspaces:
            ws_list = []
            w_set = set()
            outputs = await self.i3.get_outputs()
            for output in outputs:
                if output.active:
                    ws_list.append(output.current_workspace)
            for ws in tree.workspaces():
                if ws.name in ws_list:
                    for w in ws.leaves():
                        w_set.add(w.window)
            return w_set
        elif PER_OUTPUT:
            w_set = set()
            focused_output = focused_ws.ipc_data['output']
            for ws in tree.workspaces():
                if ws.ipc_data['output'] == focused_output:
                    for w in ws.leaves():
                        w_set.add(w.window)
            return w_set
        else:
            return set(w.window for w in tree.leaves())

    async def on_window_focus(self, i3conn, event):
        logging.info('got window focus event')
        if args.ignore_float and (event.container.floating == 'user_on'
                                  or event.container.floating == 'auto_on'):
            logging.info('not handling this floating window')
            return

        if self.update_task is not None:
            self.update_task.cancel()

        logging.info('scheduling task to update window list')
        self.update_task = asyncio.create_task(self.update_window_list(event.container))

    async def switch_win(self):
        logging.info('switching window')
        tree = await self.i3.get_tree()
        focused_win = tree.find_focused()
        focused_ws = focused_win.workspace()

        key = GLOBAL_KEY
        if KEYED_CONF:
            key = focused_ws.ipc_data['output'] if PER_OUTPUT else str(focused_ws.num)

        wlist = self.window_list.get(key)
        if wlist is None:
            return
        widx = self.window_index.get(key)

        windows = await self.get_valid_windows(tree, focused_ws)
        logging.info('valid windows = {}'.format(windows))

        for window_id in wlist[widx[0]:]:
            if window_id not in windows:
                wlist.remove(window_id)
            elif window_id == focused_win.window:
                widx[0] += 1
            else:
                if widx[0] < min(len(wlist), WIN_HISTORY) - 1:
                    widx[0] += 1
                else:
                    widx[0] = 0
                logging.info('focusing window id={}'.format(window_id))
                await self.i3.command('[id={}] focus'.format(window_id))
                break


async def run_server(loop):
    focus_watcher = FocusWatcher()
    focus_watcher.hydrate_state()
    await focus_watcher.connect()
    loop.add_signal_handler(signal.SIGUSR1, lambda: loop.create_task(focus_watcher.switch_win()))


def main():
    global MAX_WIN_HISTORY
    global UPDATE_DELAY
    global KEYED_CONF
    global WIN_HISTORY
    global PER_OUTPUT
    global args

    parser = ArgumentParser(prog='i3-cycle-focus-daemon',
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
    mutex_group = parser.add_mutually_exclusive_group()

    parser.add_argument('--history',
                        dest='history',
                        help='Maximum number of windows in the focus history',
                        type=int)
    parser.add_argument('--delay',
                        dest='delay',
                        help='Delay before updating focus history',
                        type=float)
    parser.add_argument('--ignore-floating',
                        dest='ignore_float',
                        action='store_true',
                        help='Ignore floating windows '
                        'when cycling and updating the focus history')
    mutex_group.add_argument('--visible-workspaces',
                             dest='visible_workspaces',
                             action='store_true',
                             help='Include windows on visible '
                             'workspaces only when cycling the focus history')
    mutex_group.add_argument('--active-workspace',
                             dest='active_workspace',
                             action='store_true',
                             help='Include windows on the '
                             'active workspace only when cycling the focus history')
    mutex_group.add_argument('--focused-workspace',
                             dest='focused_workspace',
                             action='store_true',
                             help='Include windows on the '
                             'focused workspace only when cycling the focus history')
    mutex_group.add_argument('--focused-output',
                             dest='focused_output',
                             action='store_true',
                             help='Include windows on the '
                             'focused output/screen only when cycling the focus history')
    parser.add_argument('--debug', dest='debug', action='store_true', help='Turn on debug logging')
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)

    if args.history:
        WIN_HISTORY = args.history

    MAX_WIN_HISTORY = WIN_HISTORY + 5

    if (args.delay and args.delay > 0) or args.delay == 0.0:
        UPDATE_DELAY = args.delay

    PER_OUTPUT = args.focused_output
    per_ws = args.focused_workspace
    KEYED_CONF = PER_OUTPUT or per_ws

    loop = asyncio.get_event_loop()
    loop.create_task(run_server(loop))
    loop.run_forever()
