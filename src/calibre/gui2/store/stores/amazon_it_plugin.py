# -*- coding: utf-8 -*-

from __future__ import (unicode_literals, division, absolute_import, print_function)
store_version = 1 # Needed for dynamic plugin loading

__license__ = 'GPL 3'
__copyright__ = '2011, John Schember <john@nachtimwald.com>'
__docformat__ = 'restructuredtext en'

from contextlib import closing
from lxml import html

from PyQt4.Qt import QUrl

from calibre.gui2.store import StorePlugin
from calibre import browser
from calibre.gui2 import open_url
from calibre.gui2.store.search_result import SearchResult


# This class is copy/pasted from amason_uk_plugin. Do not modify it in any
# other amazon EU plugin. Be sure to paste it into all other amazon EU plugins
# when modified.

class AmazonEUBase(StorePlugin):
    '''
    For comments on the implementation, please see amazon_plugin.py
    '''

    def open(self, parent=None, detail_item=None, external=False):

        store_link = self.store_link % self.aff_id
        if detail_item:
            self.aff_id['asin'] = detail_item
            store_link = self.store_link_details % self.aff_id
        open_url(QUrl(store_link))

    def search(self, query, max_results=10, timeout=60):
        url = self.search_url + query.encode('ascii', 'backslashreplace').replace('%', '%25').replace('\\x', '%').replace(' ', '+')
        br = browser()

        counter = max_results
        with closing(br.open(url, timeout=timeout)) as f:
            doc = html.fromstring(f.read())#.decode('latin-1', 'replace'))

            data_xpath = '//div[contains(@class, "prod")]'
            format_xpath = './/ul[contains(@class, "rsltL")]//span[contains(@class, "lrg") and not(contains(@class, "bld"))]/text()'
            asin_xpath = '@name'
            cover_xpath = './/img[@class="productImage"]/@src'
            title_xpath = './/h3[@class="newaps"]/a//text()'
            author_xpath = './/h3[@class="newaps"]//span[contains(@class, "reg")]/text()'
            price_xpath = './/ul[contains(@class, "rsltL")]//span[contains(@class, "lrg") and contains(@class, "bld")]/text()'

            for data in doc.xpath(data_xpath):
                if counter <= 0:
                    break

                # Even though we are searching digital-text only Amazon will still
                # put in results for non Kindle books (author pages). Se we need
                # to explicitly check if the item is a Kindle book and ignore it
                # if it isn't.
                format_ = ''.join(data.xpath(format_xpath))
                if 'kindle' not in format_.lower():
                    continue

                # We must have an asin otherwise we can't easily reference the
                # book later.
                asin = data.xpath(asin_xpath)
                if asin:
                    asin = asin[0]
                else:
                    continue

                cover_url = ''.join(data.xpath(cover_xpath))

                title = ''.join(data.xpath(title_xpath))
                author = ''.join(data.xpath(author_xpath))
                try:
                    if self.author_article:
                        author = author.split(self.author_article, 1)[1].split(" (")[0]
                except:
                    pass

                price = ''.join(data.xpath(price_xpath))

                counter -= 1

                s = SearchResult()
                s.cover_url = cover_url.strip()
                s.title = title.strip()
                s.author = author.strip()
                s.price = price.strip()
                s.detail_item = asin.strip()
                s.drm = SearchResult.DRM_UNKNOWN
                s.formats = 'Kindle'

                yield s

    def get_details(self, search_result, timeout):
        pass


class AmazonITKindleStore(AmazonEUBase):
    '''
    For comments on the implementation, please see amazon_plugin.py
    '''

    aff_id = {'tag': 'httpcharles07-21'}
    store_link = ('http://www.amazon.it/ebooks-kindle/b?_encoding=UTF8&'
                  'node=827182031&tag=%(tag)s&ie=UTF8&linkCode=ur2&camp=3370&creative=23322')
    store_link_details = ('http://www.amazon.it/gp/redirect.html?ie=UTF8&'
                          'location=http://www.amazon.it/dp/%(asin)s&tag=%(tag)s&'
                          'linkCode=ur2&camp=3370&creative=23322')
    search_url = 'http://www.amazon.it/s/?url=search-alias%3Ddigital-text&field-keywords='

    author_article = 'di '
