#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:fdm=marker:ai
from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

__license__   = 'GPL v3'
__copyright__ = '2013, Kovid Goyal <kovid at kovidgoyal.net>'
__docformat__ = 'restructuredtext en'

import sys, os
from threading import Thread

from PyQt4.Qt import (QPushButton, QFrame,
    QDialog, QVBoxLayout, QDialogButtonBox, QSize, QStackedWidget, QWidget,
    QLabel, Qt, pyqtSignal, QIcon, QTreeWidget, QGridLayout, QTreeWidgetItem,
    QToolButton, QItemSelectionModel)

from calibre.ebooks.oeb.polish.container import get_container
from calibre.ebooks.oeb.polish.toc import get_toc
from calibre.gui2 import Application
from calibre.gui2.progress_indicator import ProgressIndicator
from calibre.utils.logging import GUILog

class ItemView(QFrame): # {{{

    add_new_item = pyqtSignal(object, object)

    def __init__(self, parent):
        QFrame.__init__(self, parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setMinimumWidth(250)
        self.stack = s = QStackedWidget(self)
        self.l = l = QVBoxLayout()
        self.setLayout(l)
        l.addWidget(s)
        self.root_pane = rp = QWidget(self)
        self.item_pane = ip = QWidget(self)
        s.addWidget(rp)
        s.addWidget(ip)

        self.l1 = la = QLabel(_(
            'You can edit existing entries in the Table of Contents by clicking them'
            ' in the panel to the left.'))
        la.setWordWrap(True)
        l = QVBoxLayout()
        rp.setLayout(l)
        l.addWidget(la, alignment=Qt.AlignTop)
        self.add_new_to_root_button = b = QPushButton(_('Create a &new entry'))
        b.clicked.connect(self.add_new_to_root)
        l.addWidget(b, alignment=Qt.AlignTop)

    def add_new_to_root(self):
        self.add_new_item.emit(None, None)

    def __call__(self, item):
        if item is None:
            self.stack.setCurrentIndex(0)
        else:
            self.stack.setCurrentIndex(1)

# }}}

class TOCView(QWidget): # {{{

    add_new_item = pyqtSignal(object, object)

    def __init__(self, parent):
        QWidget.__init__(self, parent)
        l = self.l = QGridLayout()
        self.setLayout(l)
        self.tocw = t = QTreeWidget(self)
        t.setHeaderLabel(_('Table of Contents'))
        icon_size = 32
        t.setIconSize(QSize(icon_size, icon_size))
        t.setDragEnabled(True)
        t.setSelectionMode(t.ExtendedSelection)
        t.viewport().setAcceptDrops(True)
        t.setDropIndicatorShown(True)
        t.setDragDropMode(t.InternalMove)
        t.setAutoScroll(True)
        t.setAutoScrollMargin(icon_size*2)
        t.setDefaultDropAction(Qt.MoveAction)
        t.setAutoExpandDelay(1000)
        t.setAnimated(True)
        t.setMouseTracking(True)
        l.addWidget(t, 0, 0, 5, 3)
        self.up_button = b = QToolButton(self)
        b.setIcon(QIcon(I('arrow-up.png')))
        l.addWidget(b, 0, 3)
        b.setToolTip(_('Move current item up'))
        b.clicked.connect(self.move_up)
        self.del_button = b = QToolButton(self)
        b.setIcon(QIcon(I('trash.png')))
        l.addWidget(b, 2, 3)
        b.setToolTip(_('Remove all selected items'))
        b.clicked.connect(self.del_items)
        self.down_button = b = QToolButton(self)
        b.setIcon(QIcon(I('arrow-down.png')))
        l.addWidget(b, 4, 3)
        b.setToolTip(_('Move current item down'))
        b.clicked.connect(self.move_down)
        self.expand_all_button = b = QPushButton(_('&Expand all'))
        col = 5
        l.addWidget(b, col, 0)
        b.clicked.connect(self.tocw.expandAll)
        self.collapse_all_button = b = QPushButton(_('&Collapse all'))
        b.clicked.connect(self.tocw.collapseAll)
        l.addWidget(b, col, 1)
        self.default_msg = _('Double click on an entry to change the text')
        self.hl = hl = QLabel(self.default_msg)
        l.addWidget(hl, col, 2, 1, -1)
        self.item_view = i = ItemView(self)
        i.add_new_item.connect(self.add_new_item)
        l.addWidget(i, 0, 4, col, 1)

        l.setColumnStretch(2, 10)

    def event(self, e):
        if e.type() == e.StatusTip:
            txt = unicode(e.tip()) or self.default_msg
            self.hl.setText(txt)
        return super(TOCView, self).event(e)

    def item_title(self, item):
        return unicode(item.data(0, Qt.DisplayRole).toString())

    def del_items(self):
        for item in self.tocw.selectedItems():
            p = item.parent() or self.root
            p.removeChild(item)

    def move_down(self):
        item = self.tocw.currentItem()
        if item is None:
            if self.root.childCount() == 0:
                return
            item = self.root.child(0)
            self.tocw.setCurrentItem(item, 0, QItemSelectionModel.ClearAndSelect)
            self.tocw.scrollToItem(item)
            return
        parent = item.parent() or self.root
        idx = parent.indexOfChild(item)
        if idx == parent.childCount() - 1:
            # At end of parent, need to become sibling of parent
            if parent is self.root:
                return
            gp = parent.parent() or self.root
            parent.removeChild(item)
            gp.insertChild(gp.indexOfChild(parent)+1, item)
        else:
            sibling = parent.child(idx+1)
            parent.removeChild(item)
            sibling.insertChild(0, item)
        self.tocw.setCurrentItem(item, 0, QItemSelectionModel.ClearAndSelect)
        self.tocw.scrollToItem(item)

    def move_up(self):
        item = self.tocw.currentItem()
        if item is None:
            if self.root.childCount() == 0:
                return
            item = self.root.child(self.root.childCount()-1)
            self.tocw.setCurrentItem(item, 0, QItemSelectionModel.ClearAndSelect)
            self.tocw.scrollToItem(item)
            return
        parent = item.parent() or self.root
        idx = parent.indexOfChild(item)
        if idx == 0:
            # At end of parent, need to become sibling of parent
            if parent is self.root:
                return
            gp = parent.parent() or self.root
            parent.removeChild(item)
            gp.insertChild(gp.indexOfChild(parent), item)
        else:
            sibling = parent.child(idx-1)
            parent.removeChild(item)
            sibling.addChild(item)
        self.tocw.setCurrentItem(item, 0, QItemSelectionModel.ClearAndSelect)
        self.tocw.scrollToItem(item)

    def update_status_tip(self, item):
        c = item.data(0, Qt.UserRole).toPyObject()
        frag = c.frag or ''
        if frag:
            frag = '#'+frag
        item.setStatusTip(0, _('<b>Title</b>: {0} <b>Dest</b>: {1}{2}').format(
            c.title, c.dest, frag))

    def data_changed(self, top_left, bottom_right):
        for r in xrange(top_left.row(), bottom_right.row()+1):
            idx = self.tocw.model().index(r, 0, top_left.parent())
            new_title = unicode(idx.data(Qt.DisplayRole).toString()).strip()
            toc = idx.data(Qt.UserRole).toPyObject()
            toc.title = new_title or _('(Untitled)')
            item = self.tocw.itemFromIndex(idx)
            self.update_status_tip(item)

    def __call__(self, ebook):
        self.ebook = ebook
        self.toc = get_toc(self.ebook)
        blank = self.blank = QIcon(I('blank.png'))

        def process_item(node, parent):
            for child in node:
                c = QTreeWidgetItem(parent)
                c.setData(0, Qt.DisplayRole, child.title or _('(Untitled)'))
                c.setData(0, Qt.UserRole, child)
                c.setFlags(Qt.ItemIsDragEnabled|Qt.ItemIsEditable|Qt.ItemIsEnabled|
                           Qt.ItemIsSelectable|Qt.ItemIsDropEnabled)
                c.setData(0, Qt.DecorationRole, blank)
                self.update_status_tip(c)
                process_item(child, c)

        root = self.root = self.tocw.invisibleRootItem()
        root.setData(0, Qt.UserRole, self.toc)
        process_item(self.toc, root)
        self.tocw.model().dataChanged.connect(self.data_changed)
        self.tocw.currentItemChanged.connect(self.current_item_changed)

    def current_item_changed(self, current, previous):
        self.item_view(current)

# }}}

class TOCEditor(QDialog): # {{{

    explode_done = pyqtSignal()

    def __init__(self, pathtobook, title=None, parent=None):
        QDialog.__init__(self, parent)
        self.pathtobook = pathtobook

        t = title or os.path.basename(pathtobook)
        self.setWindowTitle(_('Edit the ToC in %s')%t)
        self.setWindowIcon(QIcon(I('highlight_only_on.png')))

        l = self.l = QVBoxLayout()
        self.setLayout(l)

        self.stacks = s = QStackedWidget(self)
        l.addWidget(s)
        self.loading_widget = lw = QWidget(self)
        s.addWidget(lw)
        ll = self.ll = QVBoxLayout()
        lw.setLayout(ll)
        self.pi = pi = ProgressIndicator()
        pi.setDisplaySize(200)
        pi.startAnimation()
        ll.addWidget(pi, alignment=Qt.AlignHCenter|Qt.AlignCenter)
        la = self.la = QLabel(_('Loading %s, please wait...')%t)
        la.setStyleSheet('QLabel { font-size: 20pt }')
        ll.addWidget(la, alignment=Qt.AlignHCenter|Qt.AlignTop)
        self.toc_view = TOCView(self)
        s.addWidget(self.toc_view)

        bb = self.bb = QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        l.addWidget(bb)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)

        self.explode_done.connect(self.read_toc, type=Qt.QueuedConnection)

        self.resize(950, 630)

    def start(self):
        t = Thread(target=self.explode)
        t.daemon = True
        self.log = GUILog()
        t.start()

    def explode(self):
        self.ebook = get_container(self.pathtobook, log=self.log)
        if not self.isVisible():
            return
        self.explode_done.emit()

    def read_toc(self):
        self.pi.stopAnimation()
        self.toc_view(self.ebook)
        self.stacks.setCurrentIndex(1)

# }}}

if __name__ == '__main__':
    app = Application([], force_calibre_style=True)
    app
    d = TOCEditor(sys.argv[-1])
    d.start()
    d.exec_()
    del d # Needed to prevent sigsegv in exit cleanup

