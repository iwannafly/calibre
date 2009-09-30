#!/usr/bin/env  python

__license__   = 'GPL v3'
__copyright__ = '2009, Rick Kellogg'
'''
java.dzone.com
'''

from calibre.web.feeds.news import BasicNewsRecipe

class Engadget(BasicNewsRecipe):
    title                 = u'Javalobby'
    __author__            = 'Rick Kellogg'
    description           = 'news'
    language = 'en'
    oldest_article        = 7
    max_articles_per_feed = 100
    no_stylesheets        = True
    use_embedded_content  = False

    remove_tags =   [ dict(name='div', attrs={'class':["fivestar-static-form-item","relatedContent","pagination clearfix","addResources"]}),
		      dict(name='div', attrs={'id':["comments"]})]

    keep_only_tags = [dict(name='div', attrs={'id':["article"]})]

    feeds = [ (u'news', u'http://feeds.dzone.com/javalobby/frontpage')]

    def get_article_url(self, article):

        url = article.get('link', None)

        return url


