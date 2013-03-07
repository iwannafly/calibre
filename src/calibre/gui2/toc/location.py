#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:fdm=marker:ai
from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

__license__   = 'GPL v3'
__copyright__ = '2013, Kovid Goyal <kovid at kovidgoyal.net>'
__docformat__ = 'restructuredtext en'

from base64 import b64encode

from PyQt4.Qt import (QWidget, QGridLayout, QListWidget, QSize, Qt, QUrl,
                      pyqtSlot, pyqtSignal, QVBoxLayout, QFrame, QLabel,
                      QLineEdit)
from PyQt4.QtWebKit import QWebView, QWebPage, QWebElement

from calibre.ebooks.oeb.display.webview import load_html
from calibre.utils.logging import default_log

class Page(QWebPage): # {{{

    elem_clicked = pyqtSignal(object, object, object, object)

    def __init__(self):
        self.log = default_log
        QWebPage.__init__(self)
        self.js = None
        self.evaljs = self.mainFrame().evaluateJavaScript
        self.bridge_value = None
        nam = self.networkAccessManager()
        nam.setNetworkAccessible(nam.NotAccessible)
        self.setLinkDelegationPolicy(self.DelegateAllLinks)

    def javaScriptConsoleMessage(self, msg, lineno, msgid):
        self.log(u'JS:', unicode(msg))

    def javaScriptAlert(self, frame, msg):
        self.log(unicode(msg))

    def shouldInterruptJavaScript(self):
        return True

    @pyqtSlot(QWebElement, float)
    def onclick(self, elem, frac):
        elem_id = unicode(elem.attribute('id')) or None
        tag = unicode(elem.tagName()).lower()
        parent = elem
        loc = []
        while unicode(parent.tagName()).lower() != 'body':
            num = 0
            sibling = parent.previousSibling()
            while not sibling.isNull():
                num += 1
                sibling = sibling.previousSibling()
            loc.insert(0, num)
            parent = parent.parent()
        self.elem_clicked.emit(tag, frac, elem_id, tuple(loc))

    def load_js(self):
        if self.js is None:
            from calibre.utils.resources import compiled_coffeescript
            self.js = compiled_coffeescript('ebooks.oeb.display.utils')
            self.js += compiled_coffeescript('ebooks.oeb.polish.choose')
        self.mainFrame().addToJavaScriptWindowObject("py_bridge", self)
        self.evaljs(self.js)
# }}}

class WebView(QWebView): # {{{

    elem_clicked = pyqtSignal(object, object, object, object)

    def __init__(self, parent):
        QWebView.__init__(self, parent)
        self._page = Page()
        self._page.elem_clicked.connect(self.elem_clicked)
        self.setPage(self._page)
        raw = '''
        body { background-color: white  }
        .calibre_toc_hover:hover { cursor: pointer !important; border-top: solid 5px green !important }
        '''
        raw = '::selection {background:#ffff00; color:#000;}\n'+raw
        data = 'data:text/css;charset=utf-8;base64,'
        data += b64encode(raw.encode('utf-8'))
        self.settings().setUserStyleSheetUrl(QUrl(data))

    def load_js(self):
        self.page().load_js()

    def sizeHint(self):
        return QSize(1500, 300)
# }}}

class ItemEdit(QWidget):

    def __init__(self, parent):
        QWidget.__init__(self, parent)
        self.l = l = QGridLayout()
        self.setLayout(l)

        self.la = la = QLabel('<b>'+_(
            'Select a destination for the Table of Contents entry'))
        l.addWidget(la, 0, 0, 1, 3)

        self.dest_list = dl = QListWidget(self)
        dl.setMinimumWidth(250)
        dl.currentItemChanged.connect(self.current_changed)
        l.addWidget(dl, 1, 0)

        self.view = WebView(self)
        self.view.elem_clicked.connect(self.elem_clicked)
        l.addWidget(self.view, 1, 1)

        self.f = f = QFrame()
        f.setFrameShape(f.StyledPanel)
        f.setMinimumWidth(250)
        l.addWidget(f, 1, 2)
        l = f.l = QVBoxLayout()
        f.setLayout(l)

        f.la = la = QLabel('<p>'+_(
            'Here you can choose a destination for the Table of Contents\' entry'
            ' to point to. First choose a file from the book in the left-most panel. The'
            ' file will open in the central panel.<p>'

            'Then choose a location inside the file. To do so, simply click on'
            ' the place in the central panel that you want to use as the'
            ' destination. As you move the mouse around the central panel, a'
            ' thick green line appears, indicating the precise location'
            ' that will be selected when you click.'))
        la.setStyleSheet('QLabel { margin-bottom: 20px }')
        la.setWordWrap(True)
        l.addWidget(la)

        f.la2 = la = QLabel(_('&Name of the ToC entry:'))
        l.addWidget(la)
        self.name = QLineEdit(self)
        la.setBuddy(self.name)
        l.addWidget(self.name)

        self.base_msg = _('Currently selected destination:')
        self.dest_label = la = QLabel(self.base_msg)
        la.setTextFormat(Qt.PlainText)
        la.setWordWrap(True)
        la.setStyleSheet('QLabel { margin-top: 20px }')
        l.addWidget(la)

        l.addStretch()

    def load(self, container):
        self.container = container
        spine_names = [container.abspath_to_name(p) for p in
                       container.spine_items]
        spine_names = [n for n in spine_names if container.has_name(n)]
        self.dest_list.addItems(spine_names)

    def current_changed(self, item):
        name = self.current_name = unicode(item.data(Qt.DisplayRole).toString())
        path = self.container.name_to_abspath(name)
        # Ensure encoding map is populated
        self.container.parsed(name)
        encoding = self.container.encoding_map.get(name, None) or 'utf-8'

        load_html(path, self.view, codec=encoding,
                  mime_type=self.container.mime_map[name])
        self.view.load_js()
        self.dest_label.setText(self.base_msg + '\n' + _('File:') + ' ' +
                                name + '\n' + _('Top of the file'))

    def __call__(self, item, where):
        self.current_item, self.current_where = item, where
        self.current_name = None
        self.current_frag = None
        if item is None:
            self.dest_list.setCurrentRow(0)
            self.name.setText(_('(Untitled)'))
            self.dest_label.setText(self.base_msg + '\n' + _('None'))

    def elem_clicked(self, tag, frac, elem_id, loc):
        self.current_frag = elem_id or loc
        frac = int(round(frac * 100))
        base = _('Location: A <%s> tag inside the file')%tag
        if frac == 0:
            loctext = _('Top of the file')
        else:
            loctext =  _('Approximately %d%% from the top')%frac
        loctext = base + ' [%s]'%loctext
        self.dest_label.setText(self.base_msg + '\n' +
                    _('File:') + ' ' + self.current_name + '\n' + loctext)

    @property
    def result(self):
        return (self.current_item, self.current_where, self.current_name,
                self.current_frag)


