##    Copyright (C) 2007 Kovid Goyal kovid@kovidgoyal.net
##    This program is free software; you can redistribute it and/or modify
##    it under the terms of the GNU General Public License as published by
##    the Free Software Foundation; either version 2 of the License, or
##    (at your option) any later version.
##
##    This program is distributed in the hope that it will be useful,
##    but WITHOUT ANY WARRANTY; without even the implied warranty of
##    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
##    GNU General Public License for more details.
##
##    You should have received a copy of the GNU General Public License along
##    with this program; if not, write to the Free Software Foundation, Inc.,
##    51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
'''
Fetch a webpage and its links recursively.
'''
import sys, socket, urllib2, os, urlparse, codecs, logging, re, time
from urllib import url2pathname
from httplib import responses
from optparse import OptionParser

from libprs500 import __version__, __appname__, __author__, setup_cli_handlers
from libprs500.ebooks.BeautifulSoup import BeautifulSoup

logger = logging.getLogger('libprs500.web.fetch.simple')

class FetchError(Exception):
    pass

def basename(url):
    parts = urlparse.urlsplit(url)
    path = url2pathname(parts.path)
    res = os.path.basename(path)
    if not os.path.splitext(res)[1]:
        return 'index.html'
    return res

def save_soup(soup, target):
    f = codecs.open(target, 'w', 'utf8')
    f.write(unicode(soup))
    f.close()


class RecursiveFetcher(object):
    LINK_FILTER = tuple(re.compile(i, re.IGNORECASE) for i in 
                ('.exe\s*$', '.mp3\s*$', '.ogg\s*$', '^\s*mailto:', '^\s*$'))
    CSS_IMPORT_PATTERN = re.compile(r'\@import\s+url\((.*?)\)', re.IGNORECASE)
    
    def __init__(self, options):
        self.base_dir = os.path.abspath(os.path.expanduser(options.dir))
        if not os.path.exists(self.base_dir):
            os.makedirs(self.base_dir)
        self.default_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(options.timeout)
        self.max_recursions = options.max_recursions
        self.match_regexps  = [re.compile(i, re.IGNORECASE) for i in options.match_regexps]
        self.filter_regexps = [re.compile(i, re.IGNORECASE) for i in options.filter_regexps]
        self.max_files = options.max_files
        self.delay = options.delay
        self.last_fetch_at = 0.
        self.filemap = {}
        self.imagemap = {}
        self.stylemap = {}
        self.current_dir = self.base_dir
        self.files = 0

    def fetch_url(self, url):
        f = None
        logger.info('Fetching %s', url)
        delta = time.time() - self.last_fetch_at 
        if  delta < self.delay:
            time.sleep(delta)
        try:
            f = urllib2.urlopen(url)
        except urllib2.URLError, err:
            if hasattr(err, 'code') and responses.has_key(err.code):
                raise FetchError, responses[err.code]
            raise err
        finally:
            self.last_fetch_at = time.time()
        return f

        
    def start_fetch(self, url):
        soup = BeautifulSoup('<a href="'+url+'" />')
        print 'Working',
        res = self.process_links(soup, url, 0, into_dir='')
        print '%s saved to %s'%(url, res)
        return res
    
    def is_link_ok(self, url):
        for i in self.__class__.LINK_FILTER:
            if i.search(url):
                return False
        return True
        
    def is_link_wanted(self, url):
        if self.filter_regexps:
            for f in self.filter_regexps:
                if f.search(url):
                    return False
            return True
        elif self.match_regexps:
            for m in self.match_regexps:
                if m.search(url):
                    return True
            return False
        return True
        
    def process_stylesheets(self, soup, baseurl):
        diskpath = os.path.join(self.current_dir, 'stylesheets')
        if not os.path.exists(diskpath):
            os.mkdir(diskpath)
        c = 0
        for tag in soup.findAll(lambda tag: tag.name.lower()in ['link', 'style'] and tag.has_key('type') and tag['type'].lower() == 'text/css'):
            if tag.has_key('href'):
                iurl = tag['href']
                if not urlparse.urlsplit(iurl).scheme:
                    iurl = urlparse.urljoin(baseurl, iurl, False)
                if self.stylemap.has_key(iurl):
                    tag['href'] = self.stylemap[iurl]
                    continue
                try:
                    f = self.fetch_url(iurl)
                except Exception, err:
                    logger.warning('Could not fetch stylesheet %s', iurl)
                    logger.debug('Error: %s', str(err), exc_info=True)
                    continue
                c += 1
                stylepath = os.path.join(diskpath, 'style'+str(c)+'.css')
                self.stylemap[iurl] = stylepath
                open(stylepath, 'wb').write(f.read())
                tag['href'] = stylepath
            else:
                for ns in tag.findAll(text=True):                    
                    src = str(ns)
                    m = self.__class__.CSS_IMPORT_PATTERN.search(src)
                    if m:
                        iurl = m.group(1)
                        if not urlparse.urlsplit(iurl).scheme:
                            iurl = urlparse.urljoin(baseurl, iurl, False)
                        if self.stylemap.has_key(iurl):
                            ns.replaceWith(src.replace(m.group(1), self.stylemap[iurl]))
                            continue
                        try:
                            f = self.fetch_url(iurl)
                        except Exception, err:
                            logger.warning('Could not fetch stylesheet %s', iurl)
                            logger.debug('Error: %s', str(err), exc_info=True)
                            continue
                        c += 1
                        stylepath = os.path.join(diskpath, 'style'+str(c)+'.css')
                        self.stylemap[iurl] = stylepath
                        open(stylepath, 'wb').write(f.read())
                        ns.replaceWith(src.replace(m.group(1), stylepath))
                        
                        
    
    def process_images(self, soup, baseurl):
        diskpath = os.path.join(self.current_dir, 'images')
        if not os.path.exists(diskpath):
            os.mkdir(diskpath)
        c = 0
        for tag in soup.findAll(lambda tag: tag.name.lower()=='img' and tag.has_key('src')):
            iurl, ext = tag['src'], os.path.splitext(tag['src'])[1]
            if not ext:
                logger.info('Skipping extensionless image %s', iurl)
                continue
            if not urlparse.urlsplit(iurl).scheme:
                iurl = urlparse.urljoin(baseurl, iurl, False)
            if self.imagemap.has_key(iurl):
                tag['src'] = self.imagemap[iurl]
                continue
            try:
                f = self.fetch_url(iurl)
            except Exception, err:
                logger.warning('Could not fetch image %s', iurl)
                logger.debug('Error: %s', str(err), exc_info=True)
                continue
            c += 1
            imgpath = os.path.join(diskpath, 'img'+str(c)+ext)
            self.imagemap[iurl] = imgpath
            open(imgpath, 'wb').write(f.read())
            tag['src'] = imgpath

    def absurl(self, baseurl, tag, key): 
        iurl = tag[key]
        parts = urlparse.urlsplit(iurl)
        if not parts.netloc and not parts.path:
            return None
        if not parts.scheme:
            iurl = urlparse.urljoin(baseurl, iurl, False)
        if not self.is_link_ok(iurl):
            logger.info('Skipping invalid link: %s', iurl)
            return None
        return iurl
    
    def normurl(self, url):
        parts = list(urlparse.urlsplit(url))
        parts[4] = ''
        return urlparse.urlunsplit(parts)
                
    def localize_link(self, tag, key, path):
        parts = urlparse.urlsplit(tag[key])
        suffix = '#'+parts.fragment if parts.fragment else ''
        tag[key] = path+suffix
    
    def process_return_links(self, soup, baseurl):
        for tag in soup.findAll(lambda tag: tag.name.lower()=='a' and tag.has_key('href')):
            iurl = self.absurl(baseurl, tag, 'href')            
            if not iurl:
                continue
            nurl = self.normurl(iurl)
            if self.filemap.has_key(nurl):
                self.localize_link(tag, 'href', self.filemap[nurl])
    
    def process_links(self, soup, baseurl, recursion_level, into_dir='links'):
        c, res = 0, ''
        diskpath = os.path.join(self.current_dir, into_dir)
        if not os.path.exists(diskpath):
            os.mkdir(diskpath)
        prev_dir = self.current_dir
        try:
            self.current_dir = diskpath
            for tag in soup.findAll(lambda tag: tag.name.lower()=='a' and tag.has_key('href')):
                print '.',
                sys.stdout.flush()
                iurl = self.absurl(baseurl, tag, 'href')
                if not iurl:
                    continue
                nurl = self.normurl(iurl)
                if self.filemap.has_key(nurl):
                    self.localize_link(tag, 'href', self.filemap[nurl])
                    continue
                if self.files > self.max_files:
                    return res
                c += 1
                linkdir = 'link'+str(c) if into_dir else ''
                linkdiskpath = os.path.join(diskpath, linkdir)
                if not os.path.exists(linkdiskpath):
                    os.mkdir(linkdiskpath)
                try:
                    self.current_dir = linkdiskpath
                    f = self.fetch_url(iurl)
                    soup = BeautifulSoup(f.read())
                    logger.info('Processing images...')
                    self.process_images(soup, f.geturl())
                    self.process_stylesheets(soup, f.geturl())
                    
                    res = os.path.join(linkdiskpath, basename(iurl))
                    self.filemap[nurl] = res
                    if recursion_level < self.max_recursions:
                        logger.info('Processing links...')
                        self.process_links(soup, iurl, recursion_level+1)
                    else:
                        self.process_return_links(soup, iurl) 
                        logger.info('Recursion limit reached. Skipping %s', iurl)
                    
                    save_soup(soup, res)
                    self.localize_link(tag, 'href', res)
                except Exception, err:
                    logger.warning('Could not fetch link %s', iurl)
                    logger.debug('Error: %s', str(err), exc_info=True)
                finally:
                    self.current_dir = diskpath
                    self.files += 1                
        finally:
            self.current_dir = prev_dir
        print
        return res
    
    def __del__(self):
        socket.setdefaulttimeout(self.default_timeout)
        
def option_parser(usage='%prog URL\n\nWhere URL is for example http://google.com'):
    parser = OptionParser(usage=usage, version=__appname__+' '+__version__,
                          epilog='Created by ' + __author__)
    parser.add_option('-d', '--base-dir', help='Base directory into which URL is saved. Default is %default',
                      default='.', type='string', dest='dir')
    parser.add_option('-t', '--timeout', help='Timeout in seconds to wait for a response from the server. Default: %default s',
                      default=10, type='int', dest='timeout')
    parser.add_option('-r', '--max-recursions', help='Maximum number of levels to recurse i.e. depth of links to follow. Default %default',
                      default=1, type='int', dest='max_recursions')
    parser.add_option('-n', '--max-files', default=sys.maxint, type='int', dest='max_files',
                      help='The maximum number of files to download. This only applies to files from <a href> tags. Default is %default')
    parser.add_option('--match-regexp', default=[], action='append', dest='match_regexps',
                      help='Only links that match this regular expression will be followed. This option can be specified multiple times, in which case as long as a link matches any one regexp, it will be followed. By default all links are followed.')
    parser.add_option('--filter-regexp', default=[], action='append', dest='filter_regexps',
                      help='Any link that matches this regular expression will be ignored. This option can be specified multiple times, in which case as long as any regexp matches a link, it will be ignored.By default, no links are ignored. If both --filter-regexp and --match-regexp are specified, then --match-regexp is ignored.')
    parser.add_option('--delay', default=0, dest='delay', type='int',
                      help='Minimum interval in seconds between consecutive fetches. Default is %default s')
    parser.add_option('--verbose', help='Show detailed output information. Useful for debugging',
                      default=False, action='store_true', dest='verbose')
    return parser

def main(args=sys.argv):
    parser = option_parser()    
    options, args = parser.parse_args(args)
    if len(args) != 2:
        parser.print_help()
        return 1
    level = logging.DEBUG if options.verbose else logging.WARNING
    setup_cli_handlers(logger, level)
        
    fetcher = RecursiveFetcher(options)
    fetcher.start_fetch(args[1])
    

if __name__ == '__main__':    
    sys.exit(main())