#!/usr/bin/env python
#
# Copyright 2007 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import webapp2,sys
import os.path
import ranker

from lxml import html
from google.appengine.ext import ndb

class InitDBHandler(webapp2.RequestHandler):
    def get(self):

        q = ranker.Group.query()
        for r in q.fetch():
            r.key.delete()

        for fname in ['Threat Level Midnight.html', 'Boats & Hozen.html']:

            folder = os.path.dirname(os.path.realpath(__file__))
            f = open(fname, 'r')
            text = f.read()

            tree = html.fromstring(text)
            alltrs = tree.xpath("//tbody/tr")
            
            group = ranker.Group()
            
            for i,row in enumerate(alltrs):
                if i:
                    # break down each <tr> row into the individual <td> children
                    # and then get the text from each one of them.  stick that
                    # text into a list.
                    row = [c.text for c in row.getchildren()]
                    if i == 1:
                        group.name = row[2].encode('utf-8','ignore')
                        
                    toon = row[4]
                    if toon == None:
                        continue
                    elif toon == 'Aerie Peak':
                        toon = row[3]
                    elif toon in ['Tank','Heals','Heals/DPS','DPS']:
                        toon = row[2]

                    group.toons.append(toon.encode('utf-8','ignore'))
                        
                group.put()
                    
# The new Battle.net Mashery API requires an API key when using it.  This
# method stores an API in the datastore so it can used in later page requests.
class SetAPIKey(webapp2.RequestHandler):
    def get(self):

        # Delete all of the entities out of the apikey datastore so fresh 
        # entities can be loaded.
#        q = ranker.APIKey.query()
#        for r in q.fetch():
#            r.key.delete()

        argkey = self.request.get('key')
        if ((argkey == None) or (len(argkey) == 0)):
            self.response.write("Must pass API with 'key' argument in url")
        else:
            k = ranker.APIKey(key=self.request.get('key'))
            k.put()
            self.response.write("API Key Stored.")

app = webapp2.WSGIApplication([
    ('/', ranker.Ranker),
    ('/initdb', InitDBHandler),
    ('/setapikey', SetAPIKey),
], debug=True)
