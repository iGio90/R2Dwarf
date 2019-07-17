"""
Dwarf - Copyright (C) 2019 Giovanni Rocca (iGio90)

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <https://www.gnu.org/licenses/>
"""
import json
import os
import shutil
import time
from subprocess import *

from PyQt5.Qt import QMenu, QCursor
from PyQt5.QtCore import QObject, QThread, pyqtSignal, Qt, QSize
from PyQt5.QtGui import QStandardItemModel, QStandardItem
from PyQt5.QtWidgets import QSizePolicy, QSplitter, QScrollArea, QScroller, QFrame, QLabel, QPlainTextEdit, \
    QAction, QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QCheckBox

from lib import utils
from lib.prefs import Prefs
from lib.range import Range
from ui.dialog_input import InputDialog
from ui.widget_console import DwarfConsoleWidget
from ui.widgets.list_view import DwarfListView

#########
# PREFS #
#########
KEY_WIDESCREEN_MODE = 'r2_widescreen'


###########
# WIDGETS #
###########

class R2DecompiledText(QPlainTextEdit):

    def __init__(self, parent=None):
        super().__init__(parent=parent)

    def mousePressEvent(self, event):
        mouse_btn = event.button()
        mouse_pos = event.pos()

        clicked_offset_link = self.anchorAt(mouse_pos)
        if clicked_offset_link:
            if clicked_offset_link.startswith('offset:'):
                if mouse_btn == Qt.LeftButton:
                    _offset = clicked_offset_link.split(':')
                    self.doStuff(_offset[1])
                elif mouse_btn == Qt.RightButton:
                    _offset = clicked_offset_link.split(':')
                    _offset = _offset[1]
                    menu = QMenu()
                    menu.addAction('Copy Offset', lambda: utils.copy_hex_to_clipboard(_offset))
                    menu.exec_(QCursor.pos())

        return super().mousePressEvent(event)


class R2ScrollArea(QScrollArea):
    def __init__(self, *__args):
        super().__init__(*__args)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameStyle(QFrame.NoFrame)
        self.setFrameShadow(QFrame.Plain)
        self.viewport().setAttribute(Qt.WA_AcceptTouchEvents)
        QScroller.grabGesture(self.viewport(), QScroller.LeftMouseButtonGesture)
        self.setWidgetResizable(True)

        self.label = QLabel()
        self.label.setTextFormat(Qt.RichText)
        self.label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)

        self.setWidget(self.label)

    def clearText(self):
        self.label.clear()

    def setText(self, text):
        self.label.setText(text)

    def sizeHint(self):
        return QSize(200, 200)


class OptionsDialog(QDialog):
    def __init__(self, prefs, parent=None):
        super(OptionsDialog, self).__init__(parent)
        self._prefs = prefs

        self.setMinimumWidth(500)
        self.setContentsMargins(5, 5, 5, 5)

        layout = QVBoxLayout(self)
        options = QVBoxLayout()
        options.setContentsMargins(0, 0, 0, 20)

        options.addWidget(QLabel('UI'))

        self.widescreen_mode = QCheckBox('widescreen mode')
        self.widescreen_mode.setCheckState(Qt.Checked if self._prefs.get(
            KEY_WIDESCREEN_MODE, False) else Qt.Unchecked)
        options.addWidget(self.widescreen_mode)

        buttons = QHBoxLayout()
        cancel = QPushButton('cancel')
        cancel.clicked.connect(self.close)
        buttons.addWidget(cancel)
        accept = QPushButton('accept')
        accept.clicked.connect(self.accept)
        buttons.addWidget(accept)

        layout.addLayout(options)
        layout.addLayout(buttons)

    @staticmethod
    def show_dialog(prefs):
        dialog = OptionsDialog(prefs)
        result = dialog.exec_()

        if result == QDialog.Accepted:
            try:
                dialog._prefs.put(
                    KEY_WIDESCREEN_MODE, True if dialog.widescreen_mode.checkState() == Qt.Checked else False
                )
            except:
                pass


################
# CORE CLASSES #
################
class R2Analysis(QThread):
    onR2AnalysisFinished = pyqtSignal(name='onR2AnalysisFinished')

    def __init__(self, pipe, dwarf_range):
        super(R2Analysis, self).__init__()
        self._pipe = pipe
        self._dwarf_range = dwarf_range

    def run(self):
        self._pipe.map(self._dwarf_range)
        self._pipe.cmd('s %s' % hex(self._dwarf_range.base))
        self._pipe.cmd('e anal.from = %d; e anal.to = %d; e anal.in = raw' % (
            self._dwarf_range.base, self._dwarf_range.tail))
        self._pipe.cmd('aa')
        self._pipe.cmd('aac')
        self._pipe.cmd('aar')
        self.onR2AnalysisFinished.emit()


class R2FunctionAnalysis(QThread):
    onR2FunctionAnalysisFinished = pyqtSignal(list, name='onR2FunctionAnalysisFinished')

    def __init__(self, pipe, dwarf_range):
        super(R2FunctionAnalysis, self).__init__()
        self._pipe = pipe
        self._dwarf_range = dwarf_range

    def run(self):
        self._pipe.map(self._dwarf_range)

        function_prologue = self._pipe.cmd('?v $F')
        function_end = self._pipe.cmd('?v $FE')

        function = None

        if self._dwarf_range.module_info is not None:
            if function_prologue in self._dwarf_range.module_info.functions_map:
                function = self._dwarf_range.module_info.functions_map[function_prologue]
                try:
                    info = function.r2_info
                    if info:
                        self.onR2FunctionAnalysisFinished.emit([self._dwarf_range, info])
                        return
                except:
                    pass

        self._pipe.cmd('e anal.from = %s; e anal.to = %s; e anal.in = raw' % (function_prologue, function_end))

        self._pipe.cmd('af')
        function_info = self._pipe.cmdj('afij')
        if len(function_info) > 0:
            function_info = function_info[0]
            if function is not None:
                function.r2_info = function_info
        self.onR2FunctionAnalysisFinished.emit([self._dwarf_range, function_info])


class R2Graph(QThread):
    onR2Graph = pyqtSignal(list, name='onR2Graph')

    def __init__(self, pipe):
        super(R2Graph, self).__init__()
        self._pipe = pipe

    def run(self):
        function_prologue = int(self._pipe.cmd('?v $F'), 16)
        function = None

        if self._dwarf_range.module_info is not None:
            if function_prologue in self._dwarf_range.module_info.functions_map:
                function = self._dwarf_range.module_info.functions_map[function_prologue]
                try:
                    graph = function.r2_graph
                    if graph:
                        self.onR2Graph.emit([graph])
                        return
                except:
                    pass

        graph = self._pipe.cmd('agf')
        if function is not None:
            function.r2_graph = graph
        self.onR2Graph.emit([graph])


class R2Decompiler(QThread):
    onR2Decompiler = pyqtSignal(list, name='onR2Decompiler')

    def __init__(self, pipe, with_r2dec):
        super(R2Decompiler, self).__init__()
        self._pipe = pipe
        self._with_r2dec = with_r2dec

    def run(self):
        function_prologue = int(self._pipe.cmd('?v $F'), 16)
        function = None

        if self._dwarf_range.module_info is not None:
            if function_prologue in self._dwarf_range.module_info.functions_map:
                function = self._dwarf_range.module_info.functions_map[function_prologue]
                try:
                    decompile_data = function.r2_decompile_data
                    if decompile_data:
                        self.onR2Decompiler.emit([decompile_data])
                        return
                except:
                    pass

        if self._with_r2dec:
            decompile_data = self._pipe.cmd('pddo')
        else:
            decompile_data = self._pipe.cmd('pdc')

        if function is not None:
            function.r2_decompile_data = decompile_data
        self.onR2Decompiler.emit([decompile_data])


class R2Pipe(QObject):
    onPipeBroken = pyqtSignal(str, name='onPipeBroken')

    def __init__(self, plugin, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.plugin = plugin
        self.dwarf = plugin.app.dwarf
        self.process = None
        self._working = False

        self.r2_pipe_local_path = os.path.abspath('.r2pipe')
        if os.path.exists(self.r2_pipe_local_path):
            shutil.rmtree(self.r2_pipe_local_path)
        os.mkdir(self.r2_pipe_local_path)

        self.close()

    def close(self):
        if os.name != 'nt':
            utils.do_shell_command("pkill radare2")
        else:
            utils.do_shell_command("tskill radare2")

    def open(self):
        r2e = 'radare2'

        if os.name == 'nt':
            r2e += '.exe'
        cmd = [r2e, "-w", "-q0", '-']
        try:
            self.process = Popen(cmd, shell=False, stdin=PIPE, stdout=PIPE, bufsize=0)
        except Exception as e:
            self.onPipeBroken.emit(str(e))
        self.process.stdout.read(1)

    def cmd(self, cmd):
        try:
            ret = self._cmd_process(cmd)

            if cmd.startswith('s '):
                ptr = utils.parse_ptr(cmd[2:])
                address_info = self._cmd_process('ai')

                if len(address_info) == 0:
                    self.plugin.console.log('mapping range at %s' % hex(ptr))

                    r = Range(Range.SOURCE_TARGET, self.dwarf)
                    r.init_with_address(ptr, require_data=True)

                    self.map(r)
            return ret
        except Exception as e:
            self._working = False
            self.onPipeBroken.emit(str(e))
        return None

    def cmdj(self, cmd):
        ret = self.cmd(cmd)
        try:
            return json.loads(ret)
        except:
            return {}

    def map(self, dwarf_range):
        map_path = os.path.join(self.r2_pipe_local_path, hex(dwarf_range.base))
        if not os.path.exists(map_path):
            with open(map_path, 'wb') as f:
                f.write(dwarf_range.data)
            self.cmd('on %s %s %s' % (map_path, hex(dwarf_range.base), dwarf_range.permissions))

    def _cmd_process(self, cmd):
        if not self.process:
            return

        while self._working:
            time.sleep(.1)

        self._working = True

        cmd = cmd.strip().replace("\n", ";")
        self.process.stdin.write((cmd + '\n').encode('utf8'))
        self.process.stdin.flush()

        output = b''
        while True:
            try:
                result = self.process.stdout.read(4096)
            except:
                continue
            if result:
                if result.endswith(b'\0'):
                    output += result[:-1]
                    break

                output += result
            else:
                time.sleep(0.001)

        self._working = False
        output = output.decode('utf-8', errors='ignore')
        if output.endswith('\n'):
            output = output[:-1]
        return output


class Plugin:
    # TODO: check the if not pipe createpipe when it fails why retrying on every disasm/apply_ctx

    def __get_plugin_info__(self):
        return {
            'name': 'r2dwarf',
            'description': 'r2frida in Dwarf',
            'version': '1.0.0',
            'author': 'iGio90',
            'homepage': 'https://github.com/iGio90/Dwarf',
            'license': 'https://www.gnu.org/licenses/gpl-3.0',
        }

    def __get_top_menu_actions__(self):
        if len(self.menu_items) > 0:
            return self.menu_items

        options = QAction('Options')
        options.triggered.connect(lambda: OptionsDialog.show_dialog(self._prefs))

        self.menu_items.append(options)
        return self.menu_items

    def __get_agent__(self):
        self.app.dwarf.onReceiveCmd.connect(self._on_receive_cmd)

        # we create the first pipe here to be safe that the r2 agent is loaded before the first breakpoint
        # i.e if we start dwarf targetting a package from args and a script breaking at first open
        # dwarf will hang because r2frida try to load it's agent and frida turn to use some api uth which are
        # not usable before the breakpoint quit
        # __get_agent__ is request just after our agent load and it solved all the things
        # still not the best solution as if the pipe got broken for some reason and we re-attempt to create it
        # while we are in a bkp we will face the same shit
        self._create_pipe()

        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'agent.js'), 'r') as f:
            return f.read()

    def __init__(self, app):
        self.app = app

        # block the creation of pipe on fatal errors
        self.pipe_locker = False

        self._prefs = Prefs()
        self.pipe = None
        self.current_seek = ''
        self.with_r2dec = False
        self._working = False

        self.menu_items = []

        self.app.session_manager.sessionCreated.connect(self._on_session_created)
        self.app.session_manager.sessionStopped.connect(self._on_session_stopped)
        self.app.onUIElementCreated.connect(self._on_ui_element_created)

    def _create_pipe(self):
        if self.pipe_locker:
            return None

        self.current_seek = ''
        self.pipe = self._open_pipe()

        if self.pipe is None:
            return None

        r2_decompilers = self.pipe.cmd('e cmd.pdc=?')
        if r2_decompilers is None:
            return None
        r2_decompilers = r2_decompilers.split()
        if r2_decompilers and 'pdd' in r2_decompilers:
            self.with_r2dec = True
        self.pipe.cmd("e scr.color=2; e scr.html=1; e scr.utf8=true;")
        return self.pipe

    def _open_pipe(self):
        device = self.app.dwarf.device

        if device is None:
            return None

        pipe = R2Pipe(self)
        pipe.onPipeBroken.connect(self._on_pipe_error)

        pipe.open()
        return pipe

    def _on_disassemble(self, dwarf_range):
        if self.pipe is None:
            self._create_pipe()

        if self.disassembly_view.decompilation_view is not None:
            self.disassembly_view.decompilation_view.setParent(None)
            self.disassembly_view.decompilation_view = None
        if self.disassembly_view.graph_view is not None:
            self.disassembly_view.graph_view.setParent(None)
            self.disassembly_view.graph_view = None

        if self.pipe is not None:
            start_address = hex(dwarf_range.start_address)
            if self.current_seek != start_address:
                self.current_seek = start_address
                self.pipe.cmd('s %s' % self.current_seek)

            self.app.show_progress('r2: analyzing function')
            self._working = True

            self.r2function_analysis = R2FunctionAnalysis(self.pipe, dwarf_range)
            self.r2function_analysis.onR2FunctionAnalysisFinished.connect(self._on_finish_function_analysis)
            self.r2function_analysis.start()

            if self.call_refs_model is not None:
                self.call_refs_model.setRowCount(0)
            if self.code_xrefs_model is not None:
                self.code_xrefs_model.setRowCount(0)
        else:
            self._on_finish_function_analysis([dwarf_range, {}])

    def _on_finish_analysis(self):
        self.app.hide_progress()
        self._working = False

    def _on_finish_function_analysis(self, data):
        self.app.hide_progress()
        self._working = False

        dwarf_range = data[0]
        function_info = data[1]

        num_instructions = 0
        if 'offset' in function_info:
            dwarf_range.start_offset = function_info['offset'] - dwarf_range.base
            num_instructions = int(self.pipe.cmd('pi~?'))

        self.disassembly_view.disasm_view.start_disassemble(dwarf_range, num_instructions=num_instructions)

        if 'callrefs' in function_info:
            for ref in function_info['callrefs']:
                self.call_refs_model.appendRow([
                    QStandardItem(hex(ref['addr'])),
                    QStandardItem(hex(ref['at'])),
                    QStandardItem(ref['type'])
                ])
        if 'codexrefs' in function_info:
            for ref in function_info['codexrefs']:
                self.code_xrefs_model.appendRow([
                    QStandardItem(hex(ref['addr'])),
                    QStandardItem(hex(ref['at'])),
                    QStandardItem(ref['type'])
                ])

    def _on_finish_graph(self, data):
        self.app.hide_progress()
        self._working = False

        graph_data = data[0]

        if self._prefs.get(KEY_WIDESCREEN_MODE, False):
            if self.disassembly_view.graph_view is None:
                self.disassembly_view.graph_view = R2ScrollArea()
                self.disassembly_view.addWidget(self.disassembly_view.graph_view)
            self.disassembly_view.graph_view.setText('<pre>' + graph_data + '</pre>')
        else:
            r2_graph_view = R2ScrollArea()
            r2_graph_view.setText('<pre>' + graph_data + '</pre>')

            self.app.main_tabs.addTab(r2_graph_view, 'graph view')
            index = self.app.main_tabs.indexOf(r2_graph_view)
            self.app.main_tabs.setCurrentIndex(index)

    def _on_finish_decompiler(self, data):
        self.app.hide_progress()
        self._working = False

        decompile_data = data[0]
        if decompile_data is not None:
            if self._prefs.get(KEY_WIDESCREEN_MODE, False):
                if self.disassembly_view.decompilation_view is None:
                    self.disassembly_view.decompilation_view = R2DecompiledText()
                r2_decompiler_view = self.disassembly_view.decompilation_view
                self.disassembly_view.addWidget(self.disassembly_view.decompilation_view)
                if decompile_data is not None:
                    r2_decompiler_view.setText(
                        '<pre>' + decompile_data + '</pre>')
            else:
                r2_decompiler_view = R2DecompiledText()
                self.app.main_tabs.addTab(r2_decompiler_view, 'decompiler')
                index = self.app.main_tabs.indexOf(r2_decompiler_view)
                self.app.main_tabs.setCurrentIndex(index)
                r2_decompiler_view.appendHtml(
                    '<pre>' + decompile_data + '</pre>')

    def _on_hook_menu(self, menu, address):
        menu.addSeparator()
        r2_menu = menu.addMenu('r2')

        analysis_menu = r2_menu.addMenu('analysis')
        analysis_menu.addAction('analyze range', lambda: self.analyze_range(address))

        view_menu = r2_menu.addMenu('view')
        graph = view_menu.addAction('graph view', self.show_graph_view)
        decompile = view_menu.addAction('decompile', self.show_decompiler_view)
        if address == -1:
            graph.setEnabled(False)
            decompile.setEnabled(False)

    def _on_pipe_error(self, reason):
        should_recreate_pipe = True

        if 'Broken' in reason:
            should_recreate_pipe = False

        if should_recreate_pipe:
            self._create_pipe()

    def _on_receive_cmd(self, args):
        message, data = args
        if 'payload' in message:
            payload = message['payload']
            if payload.startswith('r2 '):
                if self.pipe is None:
                    self._create_pipe()

                cmd = message['payload'][3:]

                if cmd == 'init':
                    r2arch = self.app.dwarf.arch
                    r2bits = 32
                    if r2arch == 'arm64':
                        r2arch = 'arm'
                        r2bits = 64
                    elif r2arch == 'x64':
                        r2arch = 'x86'
                        r2bits = 64
                    elif r2arch == 'ia32':
                        r2arch = 'x86'
                    self.pipe.cmd('e asm.arch=%s; e asm.bits=%d; e asm.os=%s; e anal.arch=%s' % (
                        r2arch, r2bits, self.app.dwarf.platform, r2arch))
                    return

                try:
                    result = self.pipe.cmd(cmd)
                    self.app.dwarf._script.post({"type": 'r2', "payload": result})
                except:
                    self.app.dwarf._script.post({"type": 'r2', "payload": None})

    def _on_session_created(self):
        self.console = DwarfConsoleWidget(self.app, input_placeholder='r2', completer=False)
        self.console.onCommandExecute.connect(self.on_r2_command)

        self.app.main_tabs.addTab(self.console, 'r2')

    def _on_session_stopped(self):
        # TODO: cleanup the stuff
        if self.pipe:
            self.pipe.close()

    def _on_ui_element_created(self, elem, widget):
        if elem == 'disassembly':
            self.disassembly_view = widget
            self.disassembly_view.graph_view = None
            self.disassembly_view.decompilation_view = None

            self.disassembly_view.disasm_view.run_default_disassembler = False
            self.disassembly_view.disasm_view.onDisassemble.connect(self._on_disassemble)

            r2_function_refs = QSplitter()
            r2_function_refs.setOrientation(Qt.Vertical)

            call_refs = DwarfListView()
            self.call_refs_model = QStandardItemModel(0, 3)
            self.call_refs_model.setHeaderData(0, Qt.Horizontal, 'call refs')
            self.call_refs_model.setHeaderData(1, Qt.Horizontal, '')
            self.call_refs_model.setHeaderData(2, Qt.Horizontal, '')
            call_refs.setModel(self.call_refs_model)

            code_xrefs = DwarfListView()
            self.code_xrefs_model = QStandardItemModel(0, 3)
            self.code_xrefs_model.setHeaderData(0, Qt.Horizontal, 'code xrefs')
            self.code_xrefs_model.setHeaderData(1, Qt.Horizontal, '')
            self.code_xrefs_model.setHeaderData(2, Qt.Horizontal, '')
            code_xrefs.setModel(self.code_xrefs_model)

            r2_function_refs.addWidget(call_refs)
            r2_function_refs.addWidget(code_xrefs)

            self.disassembly_view.insertWidget(1, r2_function_refs)

            self.disassembly_view.setStretchFactor(0, 1)
            self.disassembly_view.setStretchFactor(1, 1)
            self.disassembly_view.setStretchFactor(2, 5)

            self.disassembly_view.disasm_view.menu_extra_menu_hooks.append(self._on_hook_menu)

    def analyze_range(self, hint_address=0):
        if self._working:
            utils.show_message_box('please wait for the other works to finish')
        else:
            if hint_address < 0:
                hint_address = 0
            ptr, input_ = InputDialog.input_pointer(self.app, input_content=hex(hint_address))
            if ptr > 0:
                r = Range(Range.SOURCE_TARGET, self.app.dwarf)
                r.init_with_address(ptr)

                self.app.show_progress('r2: running analysis')
                self._working = True

                self.r2analysis = R2Analysis(self.pipe, r)
                self.r2analysis.onR2AnalysisFinished.connect(self._on_finish_analysis)
                self.r2analysis.start()

    def show_decompiler_view(self):
        if self._working:
            utils.show_message_box('please wait for the other works to finish')
        else:
            self.app.show_progress('r2: decompiling function')
            self._working = True

            self.r2decompiler = R2Decompiler(self.pipe, self.with_r2dec)
            self.r2decompiler.onR2Decompiler.connect(self._on_finish_decompiler)
            self.r2decompiler.start()

    def show_graph_view(self):
        if self._working:
            utils.show_message_box('please wait for the other works to finish')
        else:
            self.app.show_progress('r2: building graph view')
            self._working = True

            self.r2graph = R2Graph(self.pipe)
            self.r2graph.onR2Graph.connect(self._on_finish_graph)
            self.r2graph.start()

    def on_r2_command(self, cmd):
        if self.pipe is None:
            self._create_pipe()

        if cmd == 'clear' or cmd == 'clean':
            self.console.clear()
        else:
            if self._working:
                self.console.log('please wait for other works to finish', time_prefix=False)
            else:
                try:
                    result = self.pipe.cmd(cmd)
                    self.console.log(result, time_prefix=False)
                except BrokenPipeError:
                    self.console.log('pipe is broken. recreating...', time_prefix=False)
                    self._create_pipe()
                    self.pipe.cmd('s %s' % self.current_seek)
