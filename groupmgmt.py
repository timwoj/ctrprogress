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
import webapp2
import gspread
import json
import logging
import os

import ranker

# Force the deadline for urlfetch to be 10 seconds (Default is 5).  For some
# reason, that first lookup for the spreadsheet takes a bit.
from google.appengine.api import urlfetch
urlfetch.set_default_fetch_deadline(20);

class GroupBuilder(webapp2.RequestHandler):
    def get(self):
#        json_key = json.load(open('timwojapitest-c345f9cd7499.json'))
#        scope = ['https://spreadsheets.google.com/feeds']
#        credentials = SignedJwtAssertionCredentials(json_key['client_email'],
#                                                    json_key['private_key'],
#                                                    scope)
#        gc = gspread.authorize(credentials)

        path = os.path.join(os.path.split(__file__)[0],'api-auth.json')
        json_key = json.load(open(path))
        gc = gspread.login(json_key['email'], json_key['password'])
        logging.info('logged in, grabbing main sheet')

        sheet = gc.open_by_key('1tvpsPzZCFupJkTT1y7RmMkuh5VsjBiiA7FvYruJbTtw')

        logging.info('getting roster sheet')
        bigroster = sheet.worksheet('BIG ROSTER BOARD')
        groupnames = bigroster.row_values(1)
        actives = bigroster.row_values(2)
        groups = list()
        for i,group in enumerate(groupnames):
            if len(group) > 0 and actives[i] != 'Disbanded':
                groups.append(group)
        logging.info('num groups: %d' % len(groups))
                
        groupcount = 0
        tooncount = 0
        for g in groups:
            logging.info('working on group %s' % g)
            groupsheet = sheet.worksheet(g)
            data = groupsheet.get_all_values()

            # build up a list of toons for the group from the spreadsheet
            toons = list()

            # each tr is a row in the table.  we care about columns 4-6, which are
            # the character name, the server, and the role.
            for i,row in enumerate(data):
                # skip the first row which is a header row
                if i == 0:
                    continue

                # get the text of the cells of the row and skip any rows where
                # column 4 is a non-breaking space.
                toon = row[3].encode('utf-8','ignore')
                if len(toon) == 0:
                    continue
                
                if row[4] != 'Aerie Peak':
                    toon += '/%s' % row[4].encode('utf-8','ignore')
                    
                toons.append(toon)
            
            toons = sorted(toons)

            # Check if this group already exists in the datastore.  We don't
            # want to overwrite existing progress data for a group if we don't
            # have to.
            query = ranker.Group.query(ranker.Group.name == g)
            results = query.fetch(1)
            
            loggroup = False
            if (len(results) == 0):
                # create a new group, but only if it has at least 5 toons in
                # it.  that's the threshold for building progress data and
                # there's no real reason to create groups with only that many 
                # toons.
                if (len(toons) >= 5):
                    newgroup = ranker.Group(name=g)
                    newgroup.brf = ranker.Progression(raidname="Blackrock Foundry",
                                                      numbosses=10)
                    newgroup.hm = ranker.Progression(raidname="Highmaul",
                                                     numbosses=7)
                    newgroup.toons = toons
                    newgroup.put()
                    loggroup = True
            else:
                # the group already exists and all we need to do is update the
                # toon list.  all of the other data stays the same.
                existing = results[0]
                existing.toons = toons
                existing.put()
                loggroup = True
                
            if loggroup:
                groupcount += 1
                tooncount += len(toons)
                self.response.write('Stored group %s with %d toons<br/>\n' % (g,len(toons)))
                
            break
                
        self.response.write('<br/>')
        self.response.write('Now managing %d groups with %d total toons<br/>' % (groupcount, tooncount))