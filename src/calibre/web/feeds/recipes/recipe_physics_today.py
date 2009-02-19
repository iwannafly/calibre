import re
from calibre.web.feeds.news import BasicNewsRecipe
from calibre import strftime

class Physicstoday(BasicNewsRecipe):
    title          = u'Physicstoday'
    __author__  = 'Hypernova'
    description           = u'Physics Today magazine'
    publisher             = 'American Institute of Physics'
    category              = 'Physics'
    language              = _('English')
    cover_url = strftime('http://ptonline.aip.org/journals/doc/PHTOAD-home/jrnls/images/medcover%m_%Y.jpg')
    oldest_article = 30
    max_articles_per_feed = 100
    no_stylesheets        = True
    use_embedded_content  = False
    needs_subscription = True
    remove_javascript     = True
    remove_tags_before = dict(name='h1')
    remove_tags =  [dict(name='div', attrs={'class':'highslide-footer'})]
    remove_tags =  [dict(name='div', attrs={'class':'highslide-header'})]
    #remove_tags =  [dict(name='a', attrs={'class':'highslide'})]
    preprocess_regexps = [
   #(re.compile(r'<!--start PHTOAD_tail.jsp -->.*</body>', re.DOTALL|re.IGNORECASE),
   (re.compile(r'<!-- END ARTICLE and footer section -->.*</body>', re.DOTALL|re.IGNORECASE),
    lambda match: '</body>'),
]

    def get_browser(self):
        br = BasicNewsRecipe.get_browser()
        if self.username is not None and self.password is not None:
            br.open('http://www.physicstoday.org/pt/sso_login.jsp')
            br.select_form(name='login')
            br['username'] = self.username
            br['password'] = self.password
            br.submit()
        return br

    feeds          = [(u'All', u'http://www.physicstoday.org/feed.xml')]