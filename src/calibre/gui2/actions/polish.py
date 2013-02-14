#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:fdm=marker:ai
from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

__license__   = 'GPL v3'
__copyright__ = '2013, Kovid Goyal <kovid at kovidgoyal.net>'
__docformat__ = 'restructuredtext en'

import os, weakref, shutil
from collections import OrderedDict
from functools import partial

from PyQt4.Qt import (QDialog, QGridLayout, QIcon, QCheckBox, QLabel, QFrame,
                      QApplication, QDialogButtonBox, Qt, QSize, QSpacerItem,
                      QSizePolicy, QTimer, QModelIndex, QTextEdit,
                      QInputDialog, QMenu)

from calibre.gui2 import error_dialog, Dispatcher, gprefs
from calibre.gui2.actions import InterfaceAction
from calibre.gui2.convert.metadata import create_opf_file
from calibre.gui2.dialogs.progress import ProgressDialog
from calibre.ptempfile import PersistentTemporaryDirectory
from calibre.utils.config_base import tweaks

class Polish(QDialog): # {{{

    def __init__(self, db, book_id_map, parent=None):
        from calibre.ebooks.oeb.polish.main import HELP
        QDialog.__init__(self, parent)
        self.db, self.book_id_map = weakref.ref(db), book_id_map
        self.setWindowIcon(QIcon(I('polish.png')))
        title = _('Polish book')
        if len(book_id_map) > 1:
            title = _('Polish %d books')%len(book_id_map)
        self.setWindowTitle(title)

        self.help_text = {
            'polish': _('<h3>About Polishing books</h3>%s')%HELP['about'],

            'subset':_('<h3>Subsetting fonts</h3>%s')%HELP['subset'],

            'metadata':_('<h3>Updating metadata</h3>'
                         '<p>This will update all metadata and covers in the'
                         ' ebook files to match the current metadata in the'
                         ' calibre library.</p><p>If the ebook file does not have'
                         ' an identifiable cover, a new cover is inserted.</p>'
                         ' <p>Note that most ebook'
                         ' formats are not capable of supporting all the'
                         ' metadata in calibre.</p>'),
            'jacket':_('<h3>Book Jacket</h3>%s')%HELP['jacket'],
            'remove_jacket':_('<h3>Remove Book Jacket</h3>%s')%HELP['jacket'],
        }

        self.l = l = QGridLayout()
        self.setLayout(l)

        self.la = la = QLabel('<b>'+_('Select actions to perform:'))
        l.addWidget(la, 0, 0, 1, 2)

        count = 0
        self.all_actions = OrderedDict([
            ('subset', _('Subset all embedded fonts')),
            ('metadata', _('Update metadata in book files')),
            ('jacket', _('Add metadata as a "book jacket" page')),
            ('remove_jacket', _('Remove a previously inserted book jacket')),
        ])
        for name, text in self.all_actions.iteritems():
            count += 1
            x = QCheckBox(text, self)
            x.stateChanged.connect(partial(self.option_toggled, name))
            l.addWidget(x, count, 0, 1, 1)
            setattr(self, 'opt_'+name, x)
            la = QLabel(' <a href="#%s">%s</a>'%(name, _('About')))
            setattr(self, 'label_'+name, x)
            la.linkActivated.connect(self.help_link_activated)
            l.addWidget(la, count, 1, 1, 1)

        count += 1
        l.addItem(QSpacerItem(10, 10, vPolicy=QSizePolicy.Expanding), count, 1, 1, 2)

        la = self.help_label = QLabel('')
        self.help_link_activated('#polish')
        la.setWordWrap(True)
        la.setTextFormat(Qt.RichText)
        la.setFrameShape(QFrame.StyledPanel)
        la.setAlignment(Qt.AlignLeft|Qt.AlignTop)
        la.setLineWidth(2)
        la.setStyleSheet('QLabel { margin-left: 75px }')
        l.addWidget(la, 0, 2, count+1, 1)
        l.setColumnStretch(2, 1)

        self.bb = bb = QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.save_button = sb = bb.addButton(_('&Save Settings'), bb.ActionRole)
        sb.clicked.connect(self.save_settings)
        self.load_button = lb = bb.addButton(_('&Load Settings'), bb.ActionRole)
        self.load_menu = QMenu(lb)
        lb.setMenu(self.load_menu)
        l.addWidget(bb, count+1, 0, 1, -1)
        self.setup_load_button()

        self.resize(QSize(900, 600))

    def save_settings(self):
        if not self.something_selected:
            return error_dialog(self, _('No actions selected'),
                _('You must select at least one action before saving'),
                                show=True)
        name, ok = QInputDialog.getText(self, _('Choose name'),
                _('Choose a name for these settings'))
        if ok:
            name = unicode(name).strip()
            if name:
                settings = {ac:getattr(self, 'opt_'+ac).isChecked() for ac in
                            self.all_actions}
                saved = gprefs.get('polish_settings', {})
                saved[name] = settings
                gprefs.set('polish_settings', saved)
                self.setup_load_button()

    def setup_load_button(self):
        saved = gprefs.get('polish_settings', {})
        m = self.load_menu
        m.clear()
        self.__actions = []
        for name in sorted(saved):
            self.__actions.append(m.addAction(name, partial(self.load_settings,
                                                            name)))
        self.load_button.setEnabled(bool(saved))

    def load_settings(self, name):
        saved = gprefs.get('polish_settings', {}).get(name, {})
        for action in self.all_actions:
            checked = saved.get(action, False)
            x = getattr(self, 'opt_'+action)
            x.blockSignals(True)
            x.setChecked(checked)
            x.blockSignals(False)

    def option_toggled(self, name, state):
        if state == Qt.Checked:
            self.help_label.setText(self.help_text[name])

    def help_link_activated(self, link):
        link = unicode(link)[1:]
        self.help_label.setText(self.help_text[link])

    @property
    def something_selected(self):
        for action in self.all_actions:
            if getattr(self, 'opt_'+action).isChecked():
                return True
        return False

    def accept(self):
        self.actions = ac = {}
        something = False
        for action in self.all_actions:
            ac[action] = bool(getattr(self, 'opt_'+action).isChecked())
            if ac[action]:
                something = True
        if not something:
            return error_dialog(self, _('No actions selected'),
                _('You must select at least one action, or click Cancel.'),
                                show=True)
        self.queue_files()
        return super(Polish, self).accept()

    def queue_files(self):
        self.tdir = PersistentTemporaryDirectory('_queue_polish')
        self.jobs = []
        if len(self.book_id_map) <= 5:
            for i, (book_id, formats) in enumerate(self.book_id_map.iteritems()):
                self.do_book(i+1, book_id, formats)
        else:
            self.queue = [(i+1, id_) for i, id_ in enumerate(self.book_id_map)]
            self.pd = ProgressDialog(_('Queueing books for polishing'),
                                     max=len(self.queue), parent=self)
            QTimer.singleShot(0, self.do_one)
            self.pd.exec_()

    def do_one(self):
        if not self.queue:
            self.pd.accept()
            return
        if self.pd.canceled:
            self.jobs = []
            self.pd.reject()
            return
        num, book_id = self.queue.pop()
        try:
            self.do_book(num, book_id, self.book_id_map[book_id])
        except:
            self.pd.reject()
        else:
            self.pd.set_value(num)
            QTimer.singleShot(0, self.do_one)

    def do_book(self, num, book_id, formats):
        base = os.path.join(self.tdir, unicode(book_id))
        os.mkdir(base)
        db = self.db()
        opf = os.path.join(base, 'metadata.opf')
        with open(opf, 'wb') as opf_file:
            mi = create_opf_file(db, book_id, opf_file=opf_file)[0]
        data = {'opf':opf, 'files':[]}
        for action in self.actions:
            data[action] = bool(getattr(self, 'opt_'+action).isChecked())
        cover = os.path.join(base, 'cover.jpg')
        if db.copy_cover_to(book_id, cover, index_is_id=True):
            data['cover'] = cover
        for fmt in formats:
            ext = fmt.replace('ORIGINAL_', '').lower()
            with open(os.path.join(base, '%s.%s'%(book_id, ext)), 'wb') as f:
                db.copy_format_to(book_id, fmt, f, index_is_id=True)
                data['files'].append(f.name)

        desc = ngettext(_('Polish %s')%mi.title,
                        _('Polish book %(nums)s of %(tot)s (%(title)s)')%dict(
                            nums=num, tot=len(self.book_id_map),
                            title=mi.title), len(self.book_id_map))
        if hasattr(self, 'pd'):
            self.pd.set_msg(_('Queueing book %(nums)s of %(tot)s (%(title)s)')%dict(
                            num=num, tot=len(self.book_id_map), title=mi.title))

        self.jobs.append((desc, data, book_id, base))
# }}}

class Report(QDialog): # {{{

    def __init__(self, parent):
        QDialog.__init__(self, parent)
        self.gui = parent
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setWindowIcon(QIcon(I('polish.png')))
        self.reports = []

        self.l = l = QGridLayout()
        self.setLayout(l)
        self.view = v = QTextEdit(self)
        v.setReadOnly(True)
        l.addWidget(self.view, 0, 0, 1, 2)

        self.ign_msg = _('Ignore remaining %d reports')
        self.ign = QCheckBox(self.ign_msg, self)
        l.addWidget(self.ign, 1, 0)

        bb = self.bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        b = self.log_button = bb.addButton(_('View full &log'), bb.ActionRole)
        b.clicked.connect(self.view_log)
        bb.button(bb.Close).setDefault(True)
        l.addWidget(bb, 1, 1)

        self.finished.connect(self.show_next, type=Qt.QueuedConnection)

        self.resize(QSize(800, 600))

    def setup_ign(self):
        self.ign.setText(self.ign_msg%len(self.reports))
        self.ign.setVisible(bool(self.reports))
        self.ign.setChecked(False)

    def __call__(self, *args):
        self.reports.append(args)
        self.setup_ign()
        if not self.isVisible():
            self.show_next()

    def show_report(self, book_title, book_id, fmts, job, report):
        from calibre.ebooks.markdown.markdown import markdown
        self.current_log = job.details
        self.setWindowTitle(_('Polishing of %s')%book_title)
        self.view.setText(markdown('# %s\n\n'%book_title + report,
                                   output_format='html4'))
        self.bb.button(self.bb.Close).setFocus(Qt.OtherFocusReason)

    def view_log(self):
        self.view.setPlainText(self.current_log)
        self.view.verticalScrollBar().setValue(0)

    def show_next(self, *args):
        if not self.reports:
            return
        if not self.isVisible():
            self.show()
        self.show_report(*self.reports.pop(0))
        self.setup_ign()

    def accept(self):
        if self.ign.isChecked():
            self.reports = []
        if self.reports:
            self.show_next()
            return
        super(Report, self).accept()

    def reject(self):
        if self.ign.isChecked():
            self.reports = []
        if self.reports:
            self.show_next()
            return
        super(Report, self).reject()
# }}}

class PolishAction(InterfaceAction):

    name = 'Polish Books'
    action_spec = (_('Polish books'), 'polish.png', None, _('P'))
    dont_add_to = frozenset(['context-menu-device'])
    action_type = 'current'

    def genesis(self):
        self.qaction.triggered.connect(self.polish_books)
        self.report = Report(self.gui)

    def location_selected(self, loc):
        enabled = loc == 'library'
        self.qaction.setEnabled(enabled)

    def get_books_for_polishing(self):
        from calibre.ebooks.oeb.polish.main import SUPPORTED
        rows = [r.row() for r in
                self.gui.library_view.selectionModel().selectedRows()]
        if not rows or len(rows) == 0:
            d = error_dialog(self.gui, _('Cannot polish'),
                    _('No books selected'))
            d.exec_()
            return None
        db = self.gui.library_view.model().db
        ans = (db.id(r) for r in rows)
        supported = set(SUPPORTED)
        for x in SUPPORTED:
            supported.add('ORIGINAL_'+x)
        ans = [(x, set( (db.formats(x, index_is_id=True) or '').split(',') )
               .intersection(supported)) for x in ans]
        ans = [x for x in ans if x[1]]
        if not ans:
            error_dialog(self.gui, _('Cannot polish'),
                _('Polishing is only supported for books in the %s'
                  ' formats. Convert to one of those formats before polishing.')
                         %_(' or ').join(sorted(SUPPORTED)), show=True)
        ans = OrderedDict(ans)
        for fmts in ans.itervalues():
            for x in SUPPORTED:
                if ('ORIGINAL_'+x) in fmts:
                    fmts.discard(x)
        return ans

    def polish_books(self):
        book_id_map = self.get_books_for_polishing()
        if not book_id_map:
            return
        d = Polish(self.gui.library_view.model().db, book_id_map, parent=self.gui)
        if d.exec_() == d.Accepted and d.jobs:
            for desc, data, book_id, base in reversed(d.jobs):
                job = self.gui.job_manager.run_job(
                    Dispatcher(self.book_polished), 'gui_polish', args=(data,),
                    description=desc)
                job.polish_args = (book_id, base, data['files'])
            if d.jobs:
                self.gui.jobs_pointer.start()
                self.gui.status_bar.show_message(
                    _('Starting polishing of %d book(s)') % len(d.jobs), 2000)

    def book_polished(self, job):
        if job.failed:
            self.gui.job_exception(job)
            return
        db = self.gui.current_db
        book_id, base, files = job.polish_args
        fmts = set()
        for path in files:
            fmt = path.rpartition('.')[-1].upper()
            if tweaks['save_original_format']:
                fmts.add(fmt)
                db.save_original_format(book_id, fmt, notify=False)
            with open(path, 'rb') as f:
                db.add_format(book_id, fmt, f, index_is_id=True)
        self.gui.status_bar.show_message(job.description + \
                (' completed'), 2000)
        try:
            shutil.rmtree(base)
            parent = os.path.dirname(base)
            os.rmdir(parent)
        except:
            pass
        self.gui.tags_view.recount()
        if self.gui.current_view() is self.gui.library_view:
            current = self.gui.library_view.currentIndex()
            if current.isValid():
                self.gui.library_view.model().current_changed(current, QModelIndex())
        self.report(db.title(book_id, index_is_id=True), book_id, fmts, job, job.result)

if __name__ == '__main__':
    app = QApplication([])
    app
    from calibre.library import db
    d = Polish(db(), {1:{'EPUB'}, 2:{'AZW3'}})
    d.exec_()

