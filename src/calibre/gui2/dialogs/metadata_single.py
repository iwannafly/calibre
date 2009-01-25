__license__   = 'GPL v3'
__copyright__ = '2008, Kovid Goyal <kovid at kovidgoyal.net>'
''' 
The dialog used to edit meta information for a book as well as 
add/remove formats
'''
import os

from PyQt4.QtCore import SIGNAL, QObject, QCoreApplication, Qt
from PyQt4.QtGui import QPixmap, QListWidgetItem, QErrorMessage, QDialog, QCompleter


from calibre.gui2 import qstring_to_unicode, error_dialog, file_icon_provider, \
                           choose_files, pixmap_to_data, choose_images, ResizableDialog
from calibre.gui2.dialogs.metadata_single_ui import Ui_MetadataSingleDialog
from calibre.gui2.dialogs.fetch_metadata import FetchMetadata
from calibre.gui2.dialogs.tag_editor import TagEditor
from calibre.gui2.dialogs.password import PasswordDialog
from calibre.ebooks import BOOK_EXTENSIONS
from calibre.ebooks.metadata import authors_to_sort_string, string_to_authors, authors_to_string
from calibre.ebooks.metadata.library_thing import login, cover_from_isbn, LibraryThingError
from calibre import islinux
from calibre.ebooks.metadata.meta import get_metadata
from calibre.utils.config import prefs
from calibre.customize.ui import run_plugins_on_import

class Format(QListWidgetItem):
    def __init__(self, parent, ext, size, path=None):
        self.path = path
        self.ext = ext
        self.size = float(size)/(1024*1024)
        text = '%s (%.2f MB)'%(self.ext.upper(), self.size)
        QListWidgetItem.__init__(self, file_icon_provider().icon_from_ext(ext), 
                                 text, parent, QListWidgetItem.UserType)

class AuthorCompleter(QCompleter):
    
    def __init__(self, db):
        all_authors = db.all_authors()
        all_authors.sort(cmp=lambda x, y : cmp(x[1], y[1]))
        QCompleter.__init__(self, [x[1] for x in all_authors])

class MetadataSingleDialog(ResizableDialog, Ui_MetadataSingleDialog):
    
    def do_reset_cover(self, *args):
        pix = QPixmap(':/images/book.svg')
        self.cover.setPixmap(pix)
        self.cover_changed = True
    
    def select_cover(self, checked):
        files = choose_images(self, 'change cover dialog', 
                             u'Choose cover for ' + qstring_to_unicode(self.title.text()))
        if not files:
            return
        _file = files[0]
        if _file:
            _file = os.path.abspath(_file)
            if not os.access(_file, os.R_OK):
                d = error_dialog(self.window, _('Cannot read'), 
                        _('You do not have permission to read the file: ') + _file)
                d.exec_()
                return
            cf, cover = None, None
            try:
                cf = open(_file, "rb")
                cover = cf.read()
            except IOError, e: 
                d = error_dialog(self.window, _('Error reading file'),
                        _("<p>There was an error reading from file: <br /><b>") + _file + "</b></p><br />"+str(e))
                d.exec_()
            if cover:
                pix = QPixmap()
                pix.loadFromData(cover)
                if pix.isNull():
                    d = error_dialog(self.window, _file + " is not a valid picture")
                    d.exec_()
                else:
                    self.cover_path.setText(_file)
                    self.cover.setPixmap(pix)
                    self.cover_changed = True
                    self.cpixmap = pix                  
    
    
    def add_format(self, x):
        files = choose_files(self, 'add formats dialog', 
                             "Choose formats for " + qstring_to_unicode((self.title.text())),
                             [('Books', BOOK_EXTENSIONS)])
        if not files: 
            return      
        for _file in files:
            _file = os.path.abspath(_file)
            if not os.access(_file, os.R_OK):
                QErrorMessage(self.window).showMessage("You do not have "+\
                                    "permission to read the file: " + _file)
                continue
            _file = run_plugins_on_import(_file)
            size = os.stat(_file).st_size
            ext = os.path.splitext(_file)[1].lower().replace('.', '')
            for row in range(self.formats.count()):
                fmt = self.formats.item(row)
                if fmt.ext == ext:
                    self.formats.takeItem(row)
                    break
            Format(self.formats, ext, size, path=_file)
            self.formats_changed = True
    
    def remove_format(self, x):
        rows = self.formats.selectionModel().selectedRows(0)
        for row in rows:
            self.formats.takeItem(row.row())
            self.formats_changed = True
    
    def set_cover(self):
        row = self.formats.currentRow()
        fmt = self.formats.item(row)
        ext = fmt.ext.lower()
        if fmt.path is None:
            stream = self.db.format(self.row, ext, as_file=True)
        else:
            stream = open(fmt.path, 'r+b')
        try:
            mi = get_metadata(stream, ext)
        except:
            error_dialog(self, _('Could not read metadata'), 
                         _('Could not read metadata from %s format')%ext).exec_()
            return
        cdata = None
        if mi.cover and os.access(mi.cover, os.R_OK):
            cdata = open(mi.cover).read()
        elif mi.cover_data[1] is not None:
            cdata = mi.cover_data[1]
        if cdata is None:
            error_dialog(self, _('Could not read cover'), 
                         _('Could not read cover from %s format')%ext).exec_()
            return
        pix = QPixmap()
        pix.loadFromData(cdata)
        if pix.isNull():
            error_dialog(self, _('Could not read cover'), 
                         _('The cover in the %s format is invalid')%ext).exec_()
            return
        self.cover.setPixmap(pix)
        self.cover_changed = True
        self.cpixmap = pix
    
    def sync_formats(self):
        old_extensions, new_extensions, paths = set(), set(), {}
        for row in range(self.formats.count()):
            fmt = self.formats.item(row)
            ext, path = fmt.ext.lower(), fmt.path
            if 'unknown' in ext.lower():
                ext = None
            if path:
                new_extensions.add(ext)
                paths[ext] = path
            else:
                old_extensions.add(ext)
        for ext in new_extensions:
            self.db.add_format(self.row, ext, open(paths[ext], 'rb'), notify=False)
        db_extensions = set([f.lower() for f in self.db.formats(self.row).split(',')])
        extensions = new_extensions.union(old_extensions)
        for ext in db_extensions:
            if ext not in extensions:
                self.db.remove_format(self.row, ext, notify=False)
    
    def __init__(self, window, row, db, accepted_callback=None):
        ResizableDialog.__init__(self, window)
        self.bc_box.layout().setAlignment(self.cover, Qt.AlignCenter|Qt.AlignHCenter)
        self.splitter.setStretchFactor(100, 1)
        self.db = db
        self.accepted_callback = accepted_callback
        self.id = db.id(row)
        self.row = row
        self.cover_data = None
        self.formats_changed = False
        self.cover_changed = False
        self.cpixmap = None
        self.cover.setAcceptDrops(True)
        self._author_completer = AuthorCompleter(self.db)
        self.authors.setCompleter(self._author_completer)
        self.connect(self.cover, SIGNAL('cover_changed()'), self.cover_dropped)
        QObject.connect(self.cover_button, SIGNAL("clicked(bool)"), \
                                                    self.select_cover)
        QObject.connect(self.add_format_button, SIGNAL("clicked(bool)"), \
                                                    self.add_format)
        QObject.connect(self.remove_format_button, SIGNAL("clicked(bool)"), \
                                                self.remove_format)
        QObject.connect(self.fetch_metadata_button, SIGNAL('clicked()'), 
                        self.fetch_metadata)
        
        QObject.connect(self.fetch_cover_button, SIGNAL('clicked()'), 
                        self.fetch_cover)
        QObject.connect(self.tag_editor_button, SIGNAL('clicked()'), 
                        self.edit_tags)
        QObject.connect(self.remove_series_button, SIGNAL('clicked()'),
                        self.remove_unused_series)
        QObject.connect(self.auto_author_sort, SIGNAL('clicked()'),
                        self.deduce_author_sort)
        self.connect(self.button_set_cover, SIGNAL('clicked()'), self.set_cover)
        self.connect(self.reset_cover, SIGNAL('clicked()'), self.do_reset_cover)
        self.connect(self.swap_button, SIGNAL('clicked()'), self.swap_title_author)
        self.timeout = float(prefs['network_timeout'])
        self.title.setText(db.title(row))
        isbn = db.isbn(self.id, index_is_id=True)
        if not isbn:
            isbn = ''
        self.isbn.setText(isbn)
        au = self.db.authors(row)
        if au:
            au = [a.strip().replace('|', ',') for a in au.split(',')]
            self.authors.setText(authors_to_string(au))
        else:
            self.authors.setText('')
        aus = self.db.author_sort(row)
        self.author_sort.setText(aus if aus else '')
        tags = self.db.tags(row)
        self.tags.setText(tags if tags else '')
        rating = self.db.rating(row)
        if rating > 0: 
            self.rating.setValue(int(rating/2.))
        comments = self.db.comments(row)
        self.comments.setPlainText(comments if comments else '')
        cover = self.db.cover(row)
        
        exts = self.db.formats(row)
        if exts:
            exts = exts.split(',')        
            for ext in exts:
                if not ext:
                    ext = ''
                size = self.db.sizeof_format(row, ext)
                Format(self.formats, ext, size)
        
            
        self.initialize_series_and_publisher()
            
        self.series_index.setValue(self.db.series_index(row))
        QObject.connect(self.series, SIGNAL('currentIndexChanged(int)'), self.enable_series_index)
        QObject.connect(self.series, SIGNAL('editTextChanged(QString)'), self.enable_series_index)
        QObject.connect(self.password_button, SIGNAL('clicked()'), self.change_password) 

        self.show()
        height_of_rest = self.frameGeometry().height() - self.cover.height()
        width_of_rest  = self.frameGeometry().width() - self.cover.width()
        ag = QCoreApplication.instance().desktop().availableGeometry(self)
        self.cover.MAX_HEIGHT = ag.height()-(25 if islinux else 0)-height_of_rest
        self.cover.MAX_WIDTH = ag.width()-(25 if islinux else 0)-width_of_rest
        if cover:
            pm = QPixmap()
            pm.loadFromData(cover)
            if not pm.isNull(): 
                self.cover.setPixmap(pm)
    
    def deduce_author_sort(self):
        au = unicode(self.authors.text())
        authors = string_to_authors(au)
        self.author_sort.setText(authors_to_sort_string(authors))
    
    def swap_title_author(self):
        title = self.title.text()
        self.title.setText(self.authors.text())
        self.authors.setText(title)
        self.author_sort.setText('')

    def cover_dropped(self):
        self.cover_changed = True
    
    def initialize_series_and_publisher(self):
        all_series = self.db.all_series()
        all_series.sort(cmp=lambda x, y : cmp(x[1], y[1]))
        series_id = self.db.series_id(self.row)
        idx, c = None, 0
        for i in all_series:
            id, name = i
            if id == series_id:
                idx = c
            self.series.addItem(name)
            c += 1
        
        self.series.lineEdit().setText('')
        if idx is not None:
            self.series.setCurrentIndex(idx)
            self.enable_series_index()
        
        pl = self.series.parentWidget().layout()
        for i in range(pl.count()):
            l =  pl.itemAt(i).layout()
            if l:
                l.invalidate()
                l.activate()
        
        all_publishers = self.db.all_publishers()
        all_publishers.sort(cmp=lambda x, y : cmp(x[1], y[1]))
        publisher_id = self.db.publisher_id(self.row)
        idx, c = None, 0
        for i in all_publishers:
            id, name = i
            if id == publisher_id:
                idx = c
            self.publisher.addItem(name)
            c += 1
        
        self.publisher.setEditText('')
        if idx is not None:
            self.publisher.setCurrentIndex(idx)
        
                
        self.layout().activate()
    
    def edit_tags(self):
        d = TagEditor(self, self.db, self.row)
        d.exec_()
        if d.result() == QDialog.Accepted:
            tag_string = ', '.join(d.tags)
            self.tags.setText(tag_string)
    
    def lt_password_dialog(self):
        return PasswordDialog(self, 'LibraryThing account', 
                 _('<p>Enter your username and password for <b>LibraryThing.com</b>. <br/>If you do not have one, you can <a href=\'http://www.librarything.com\'>register</a> for free!.</p>'))
    
    def change_password(self):
        d = self.lt_password_dialog() 
        d.exec_()
    
    def fetch_cover(self):
        isbn   = qstring_to_unicode(self.isbn.text())
        if isbn:
            d = self.lt_password_dialog() 
            if not d.username() or not d.password():
                d.exec_()
                if d.result() != PasswordDialog.Accepted:
                    return
            self.fetch_cover_button.setEnabled(False)
            self.setCursor(Qt.WaitCursor)
            QCoreApplication.instance().processEvents()
            try:
                login(d.username(), d.password(), force=False)
                cover_data = cover_from_isbn(isbn, timeout=self.timeout)[0]
            
                pix = QPixmap()
                pix.loadFromData(cover_data)
                if pix.isNull():
                    error_dialog(self.window, "The cover is not a valid picture").exec_()
                else:
                    self.cover.setPixmap(pix)
                    self.cover_changed = True
                    self.cpixmap = pix
            except LibraryThingError, err:
                error_dialog(self, _('Could not fetch cover'), _('<b>Could not fetch cover.</b><br/>')+repr(err)).exec_()
            finally:
                self.fetch_cover_button.setEnabled(True)
                self.unsetCursor()
                
        else:
            error_dialog(self, _('Cannot fetch cover'), _('You must specify the ISBN identifier for this book.')).exec_()
                
    
    def fetch_metadata(self):
        isbn   = qstring_to_unicode(self.isbn.text())
        title  = qstring_to_unicode(self.title.text())
        author = string_to_authors(unicode(self.authors.text()))[0]
        publisher = qstring_to_unicode(self.publisher.currentText()) 
        if isbn or title or author or publisher:
            d = FetchMetadata(self, isbn, title, author, publisher, self.timeout)
            d.exec_()
            if d.result() == QDialog.Accepted:
                book = d.selected_book()
                if book:
                    self.title.setText(book.title)
                    self.authors.setText(authors_to_string(book.authors))
                    if book.author_sort: self.author_sort.setText(book.author_sort)
                    if book.publisher: self.publisher.setEditText(book.publisher)
                    if book.isbn: self.isbn.setText(book.isbn)
                    summ = book.comments
                    if summ:
                        prefix = qstring_to_unicode(self.comments.toPlainText())
                        if prefix:
                            prefix += '\n'
                        self.comments.setText(prefix + summ)
        else:
            error_dialog(self, 'Cannot fetch metadata', 'You must specify at least one of ISBN, Title, Authors or Publisher')
             
    def enable_series_index(self, *args):
        self.series_index.setEnabled(True)
    
    def remove_unused_series(self):
        self.db.remove_unused_series()
        idx = qstring_to_unicode(self.series.currentText())
        self.series.clear()
        self.initialize_series()
        if idx:
            for i in range(self.series.count()):
                if qstring_to_unicode(self.series.itemText(i)) == idx:
                    self.series.setCurrentIndex(i)
                    break
        
    
    def accept(self):
        if self.formats_changed:
            self.sync_formats()
        title = qstring_to_unicode(self.title.text())
        self.db.set_title(self.id, title, notify=False)
        au = unicode(self.authors.text())
        if au: 
            self.db.set_authors(self.id, string_to_authors(au), notify=False)
        aus = qstring_to_unicode(self.author_sort.text())
        if aus:
            self.db.set_author_sort(self.id, aus, notify=False)
        self.db.set_isbn(self.id, qstring_to_unicode(self.isbn.text()), notify=False)
        self.db.set_rating(self.id, 2*self.rating.value(), notify=False)
        self.db.set_publisher(self.id, qstring_to_unicode(self.publisher.currentText()), notify=False)
        self.db.set_tags(self.id, qstring_to_unicode(self.tags.text()).split(','), notify=False)
        self.db.set_series(self.id, qstring_to_unicode(self.series.currentText()), notify=False)
        self.db.set_series_index(self.id, self.series_index.value(), notify=False)
        self.db.set_comment(self.id, qstring_to_unicode(self.comments.toPlainText()), notify=False)
        if self.cover_changed:
            self.db.set_cover(self.id, pixmap_to_data(self.cover.pixmap()))
        QDialog.accept(self)
        if callable(self.accepted_callback):
            self.accepted_callback(self.id)
