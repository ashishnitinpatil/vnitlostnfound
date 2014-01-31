import urllib
import logging
import urlparse
import re
import os
import sys
import datetime
import string
import webapp2
from google.appengine.ext.webapp import template
from google.appengine.ext import db
from google.appengine.api import urlfetch
from google.appengine.api import memcache


class Item(db.Model):
    """
    Databasel Model to store each found items.
    """
    item_type = db.StringProperty(required=True)

    title = db.StringProperty(required=True)
    date = db.StringProperty(required=True)
    description = db.TextProperty(required=True)
    location = db.StringProperty(required=True)
    img_url = db.LinkProperty()
    tags = db.ListProperty(basestring, required=True)

    owner = db.StringProperty(required=True)
    phone = db.StringProperty(required=True)
    email = db.EmailProperty()
    other_contact = db.TextProperty()

    created = db.DateTimeProperty(auto_now_add=True)


class MainHandler(webapp2.RequestHandler):
    def get(self):
        """
        Displays latest additions to database (latest first).
        """
        items = memcache.get("most_recent")
        if not items:
            items = db.GqlQuery(
                "SELECT * FROM Item ORDER BY created DESC").fetch(25)
            memcache.set(key="most_recent", value=items)
        template_values = {'items': items, 'type': "All items"}
        path = "templates/index.html"
        self.response.out.write(template.render(path, template_values))


class FeedHandler(webapp2.RequestHandler):
    def get(self):
        """
        Renders XML RSS feed of the items in db (latest first).
        """
        to_render = memcache.get("_feed_")
        if not to_render:
            items = db.GqlQuery(
                "SELECT * FROM Item ORDER BY created DESC").fetch(25)
            template_values = {'items': items}
            path = "templates/feed.html"
            to_render = template.render(path, template_values)
            memcache.set(key="_feed_", value=to_render)
        self.response.headers['Content-Type'] = 'application/rss'
        self.response.out.write(to_render)


class LostHandler(webapp2.RequestHandler):
    def get(self):
        """
        Displays latest lost additions to database (latest first).
        """
        to_render = memcache.get("most_recent_lost")
        if not to_render:
            items = db.GqlQuery(
                "SELECT * FROM Item WHERE item_type='lost' ORDER BY created DESC").fetch(25)
            template_values = {'items': items, 'type': "Lost items"}
            path = "templates/index.html"
            to_render = template.render(path, template_values)
            memcache.set(key="most_recent_lost", value=to_render)
        self.response.out.write(to_render)


class FoundHandler(webapp2.RequestHandler):
    def get(self):
        """
        Displays latest found additions to database (latest first).
        """
        to_render = memcache.get("most_recent_found")
        if not to_render:
            items = db.GqlQuery(
                "SELECT * FROM Item WHERE item_type='found' ORDER BY created DESC").fetch(25)
            template_values = {'items': items, 'type': "Found items"}
            path = "templates/index.html"
            to_render = template.render(path, template_values)
            memcache.set(key="most_recent_found", value=to_render)
        self.response.out.write(to_render)


class SubmitHandler(webapp2.RequestHandler):
    def get(self):
        if self.request.get("q") == "bad_captcha":
            bad_captcha = True
        else:
            bad_captcha = False
        path = "templates/form.html"
        today = datetime.datetime.today()
        template_values = {'today': today.isoformat(" ").split()[0],
                           'bad_captcha': bad_captcha}
        self.response.out.write(template.render(path, template_values))

    def post(self):
        # First verify the reCaptcha & then store the item if good to go
        recaptcha_challenge = self.request.get("recaptcha_challenge_field")
        recaptcha_response = self.request.get("recaptcha_response_field")
        remoteIp = self.request.remote_addr
        captcha_ok, captcha_msg = self.reCaptcha(recaptcha_challenge,
                                                 remoteIp,
                                                 recaptcha_response)
        if captcha_ok:
            clean_tags = [tag.strip().upper() for tag in
                                self.request.get("tags").split(',')]
            if len(clean_tags) > 3:
                clean_tags = clean_tags[:3]
            for tag in clean_tags:
                memcache.delete("_tag_"+str(tag))
            memcache.delete("most_recent")
            memcache.delete("_feed_")
            memcache.delete("most_recent_lost")
            memcache.delete("most_recent_found")
            # Default to an image if not given
            image_url = self.request.get("url")
            if not image_url:
                image_url = "http://i.imgur.com/0yWozO3.png"
            new_item = Item(
                            item_type     = self.request.get("type"),
                            title         = self.request.get("title"),
                            location      = self.request.get("location"),
                            date          = self.request.get("date"),
                            img_url       = image_url,
                            tags          = clean_tags,
                            description   = self.request.get("description"),
                            owner         = self.request.get("name"),
                            phone         = self.request.get("phone"),
                            email         = self.request.get("email"),
                            other_contact = self.request.get("other_contact")
            )
            new_item.put()
            new_item_id = new_item.key().id()
            logging.info("New item with id=%s added"%new_item_id)
            self.redirect("/item/{}".format(new_item_id))

        else:
            logging.info("Captcha Error - %s"%captcha_msg)
            self.redirect("/submit?q=bad_captcha")

    def reCaptcha(self, challenge, remoteIp, response):
        PRIVATE_KEY = "6Lfovu0SAAAAAHv84Kqt0W7JcKml8E9i_oXbgJyC"
        VERIFY_URL = "http://www.google.com/recaptcha/api/verify"
        data = {"privatekey": PRIVATE_KEY,
                "challenge": challenge,
                "remoteip": remoteIp,
                "response": response}

        response = urlfetch.fetch(url=VERIFY_URL,
                          payload=urllib.urlencode(data),
                          method="POST")
        captcha_response = response.content.split("\n")
##        # Testing without captcha
##        response = "true\nSuccess"
##        captcha_response = response.split("\n")
        if captcha_response[0] == "true":
            return True, "Success"
        else:
            return False, captcha_response[1]


class TagHandler(webapp2.RequestHandler):
    def get(self, tag):
        tag = tag.upper()
        path = "templates/tag.html"
        try:
            to_render = memcache.get("_tag_"+str(tag))
            if not to_render:
                items = db.GqlQuery(
                    "SELECT * FROM Item WHERE tags = :1 ORDER BY created DESC",
                    tag).fetch(15)
                template_values = {'items': items, 'tag': tag}
                to_render = template.render(path, template_values)
                memcache.set(key="_tag_"+str(tag), value=to_render)
            self.response.out.write(to_render)
        except:
            self.response.out.write("The tag is invalid.")


class ItemPermaHandler(webapp2.RequestHandler):
    def get(self, item_id):
        path = "templates/item.html"
        try:
            to_render = memcache.get("_item_"+str(item_id))
            if not to_render:
                key = db.Key.from_path('Item', int(item_id))
                item = db.get(key)
                if not item:
                    raise KeyError
                template_values = {'item': item}
                to_render = template.render(path, template_values)
                memcache.set(key="_item_"+str(item_id), value=to_render)
            self.response.out.write(to_render)
        except:
            self.response.out.write("The item ID is invalid.")


class AboutHandler(webapp2.RequestHandler):
    def get(self):
        path = "templates/about.html"
        self.response.out.write(template.render(path, {}))


class ChangelogHandler(webapp2.RequestHandler):
    def get(self):
        path = "templates/changelog.html"
        self.response.out.write(template.render(path, {}))


class HowtoHandler(webapp2.RequestHandler):
    def get(self):
        path = "templates/howto.html"
        self.response.out.write(template.render(path, {}))


def handle_404(request, response, exception):
    logging.exception(exception)
    response.write("Oops! You seem to have wandered off! " +
                   "The requested page does not exist.")
    response.set_status(404)

def handle_500(request, response, exception):
    logging.exception(exception)
    response.write("A server error occurred! " +
                   "Report has been logged. Work underway asap.")
    response.set_status(500)

app = webapp2.WSGIApplication([('/?', MainHandler),
                               ('/submit/?', SubmitHandler),
                               ('/lost/?', LostHandler),
                               ('/found/?', FoundHandler),
                               (r'/item/(\d+)/?',ItemPermaHandler),
                               ('/tag/(\w+)/?', TagHandler),
                               ('/feed/?', FeedHandler),
                               ('/about/?', AboutHandler),
                               ('/howto/?', HowtoHandler),
                               ('/changelog/?', ChangelogHandler)],
                              debug=True)

app.error_handlers[404] = handle_404
app.error_handlers[500] = handle_500