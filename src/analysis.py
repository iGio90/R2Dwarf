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
from PyQt5.QtCore import QThread, pyqtSignal


class R2Analysis(QThread):
    onR2AnalysisFinished = pyqtSignal(list, name='onR2AnalysisFinished')

    def __init__(self, pipe, info, data, offset, is_module):
        super(R2Analysis, self).__init__()
        self._pipe = pipe
        self._info = info
        self._data = data
        self._offset = offset
        self._is_module = is_module

    def run(self):
        self._pipe.cmd('e anal.from = %d; e anal.to = %d; e anal.in = raw' % (
            self._info.base, self._info.base + self._info.size))

        if self._is_module:
            # todo: map exports/imports into r2
            pass

        self._pipe.cmd('aa')
        self._pipe.cmd('aac*')
        self._pipe.cmd('aar')
        self._pipe.cmd('afr')

        # do not use aflj - it stuck everything
        self._pipe.cmd('e scr.html=0')
        functions = self._pipe.cmd('afl').split('\n')
        self._pipe.cmd('e scr.html=1')
        func_map = {}
        for fn in functions:
            fn = fn.split(' ')
            if fn[0] != '':
                func_map[fn[len(fn) - 1]] = int(fn[0], 16)

        self.onR2AnalysisFinished.emit([self._info.base, self._data, self._offset, func_map])
