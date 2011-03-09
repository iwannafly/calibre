# -*- coding: utf-8 -*-

from __future__ import (unicode_literals, division, absolute_import, print_function)

__license__ = 'GPL 3'
__copyright__ = '2011, John Schember <john@nachtimwald.com>'
__docformat__ = 'restructuredtext en'

import cStringIO
import os
import shutil
import time
import urllib2
from cookielib import CookieJar
from contextlib import closing
from threading import Thread
from Queue import Queue

from calibre import browser, get_download_filename
from calibre.ebooks import BOOK_EXTENSIONS
from calibre.gui2 import Dispatcher
from calibre.ptempfile import PersistentTemporaryFile
from calibre.utils.ipc.job import BaseJob

class StoreDownloadJob(BaseJob):

    def __init__(self, callback, description, job_manager, db, cookie_jar, url='', filename='', save_as_loc='', add_to_lib=True, tags=[]):
        BaseJob.__init__(self, description)
        self.exception = None
        self.job_manager = job_manager
        self.db = db
        self.cookie_jar = cookie_jar
        self.args = (url, filename, save_as_loc, add_to_lib, tags)
        self.tmp_file_name = ''
        self.callback = callback
        self.log_path = None
        self._log_file = cStringIO.StringIO()
        self._log_file.write(self.description.encode('utf-8') + '\n')

    @property
    def log_file(self):
        if self.log_path is not None:
            return open(self.log_path, 'rb')
        return cStringIO.StringIO(self._log_file.getvalue())

    def start_work(self):
        self.start_time = time.time()
        self.job_manager.changed_queue.put(self)

    def job_done(self):
        self.duration = time.time() - self.start_time
        self.percent = 1
        
        try:
            os.remove(self.tmp_file_name)
        except:
            import traceback
            self.log_write(traceback.format_exc())
        
        # Dump log onto disk
        lf = PersistentTemporaryFile('store_log')
        lf.write(self._log_file.getvalue())
        lf.close()
        self.log_path = lf.name
        self._log_file.close()
        self._log_file = None

        self.job_manager.changed_queue.put(self)

    def log_write(self, what):
        self._log_file.write(what)

class StoreDownloader(Thread):
    
    def __init__(self, job_manager):
        Thread.__init__(self)
        self.daemon = True
        self.jobs = Queue()
        self.job_manager = job_manager
        self._run = True
        
    def stop(self):
        self._run = False
        self.jobs.put(None)

    def run(self):
        while self._run:
            try:
                job = self.jobs.get()
            except:
                break
            if job is None or not self._run:
                break
            
            failed, exc = False, None
            job.start_work()
            if job.kill_on_start:
                self._abort_job(job)
                continue
            
            try:
                self._download(job)
                if not self._run:
                    self._abort_job(job)
                    return

                job.percent = .8
                self._add(job)
                if not self._run:
                    self._abort_job(job)
                    return

                job.percent = .9
                if not self._run:
                    self._abort_job(job)
                    return
                self._save_as(job)
            except Exception, e:
                if not self._run:
                    return
                import traceback
                failed = True
                exc = e
                job.log_write('\nSending failed...\n')
                job.log_write(traceback.format_exc())

            if not self._run:
                break

            job.failed = failed
            job.exception = exc
            job.job_done()
            try:
                job.callback(job)
            except:
                import traceback
                traceback.print_exc()

    def _abort_job(self, job):
        job.log_write('Aborted\n')
        job.failed = False
        job.killed = True
        job.job_done()

    def _download(self, job):
        url, filename, save_loc, add_to_lib, tags = job.args
        if not url:
            raise Exception(_('No file specified to download.'))
        if not save_loc and not add_to_lib:
            # Nothing to do.
            return

        if not filename:
            filename = get_download_filename(url, job.cookie_jar)
        
        br = browser()
        br.set_cookiejar(job.cookie_jar)
        with closing(br.open(url)) as r:
            tf = PersistentTemporaryFile(suffix=filename)
            tf.write(r.read())
            job.tmp_file_name = tf.name
        
    def _add(self, job):
        url, filename, save_loc, add_to_lib, tags = job.args
        if not add_to_lib or not job.tmp_file_name:
            return
        ext = os.path.splitext(job.tmp_file_name)[1][1:].lower()
        if ext not in BOOK_EXTENSIONS:
            raise Exception(_('Not a support ebook format.'))

        from calibre.ebooks.metadata.meta import get_metadata
        with open(job.tmp_file_name) as f:
            mi = get_metadata(f, ext)
        mi.tags.extend(tags)

        id = job.db.create_book_entry(mi)
        job.db.add_format_with_hooks(id, ext.upper(), job.tmp_file_name, index_is_id=True)
    
    def _save_as(self, job):
        url, filename, save_loc, add_to_lib, tags = job.args
        if not save_loc or not job.tmp_file_name:
            return
        
        shutil.copy(job.tmp_file_name, save_loc)
        
    def download_from_store(self, callback, db, cookie_jar, url='', filename='', save_as_loc='', add_to_lib=True, tags=[]):
        description = _('Downloading %s') % filename if filename else url
        job = StoreDownloadJob(callback, description, self.job_manager, db, cookie_jar, url, filename, save_as_loc, add_to_lib, tags)
        self.job_manager.add_job(job)
        self.jobs.put(job)


class StoreDownloadMixin(object):
    
    def __init__(self):
        self.store_downloader = StoreDownloader(self.job_manager)
    
    def download_from_store(self, url='', cookie_jar=CookieJar(), filename='', save_as_loc='', add_to_lib=True, tags=[]):
        if not self.store_downloader.is_alive():
            self.store_downloader.start()
        if tags:
            if isinstance(tags, basestring):
                tags = tags.split(',')
        self.store_downloader.download_from_store(Dispatcher(self.downloaded_from_store), self.library_view.model().db, cookie_jar, url, filename, save_as_loc, add_to_lib, tags)
        self.status_bar.show_message(_('Downloading') + ' ' + filename if filename else url, 3000)
    
    def downloaded_from_store(self, job):
        if job.failed:
            self.job_exception(job, dialog_title=_('Failed to download book'))
            return
        
        self.status_bar.show_message(job.description + ' ' + _('finished'), 5000)


