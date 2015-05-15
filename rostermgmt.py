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
import json
import logging
import os

# need this stuff for the google data API
try:
  from xml.etree import ElementTree
except ImportError:
  from elementtree import ElementTree
import gdata.spreadsheet.service
import gdata.service
import atom.service
import gdata.spreadsheet
import atom

import ranker

import time
from concurrent import futures
import gc

# Force the deadline for urlfetch to be 10 seconds (Default is 5).  For some
# reason, that first lookup for the spreadsheet takes a bit.
from google.appengine.api import urlfetch
urlfetch.set_default_fetch_deadline(20);

# Grabs the ID for the worksheet from the roster spreadsheet with the
# matching group name.
def getsheetID(feed, name):
    sheet = [x for x in feed.entry if x.title.text.lower() == name.lower()][0]
    id_parts = sheet.id.text.split('/')
    return id_parts[len(id_parts) - 1]

def worker(g, feed, client, curr_key):
    t4 = time.time()
    logging.info('working on group %s' % g)
    sheetID = getsheetID(feed, g)
    sheet = client.GetListFeed(curr_key, sheetID)

    # build up a list of toons for the group from the spreadsheet
    toons = list()

    # each tr is a row in the table.  we care about columns 4-6, which are
    # the character name, the server, and the role.
    for i,entry in enumerate(sheet.entry):
        # get the text from the cells for this row that we care about,
        # assuming none of them are empty
        if entry.custom['charactername'].text == None or entry.custom['server'].text == None:
            continue

        toon = entry.custom['charactername'].text.encode('utf-8','ignore')
        if len(toon) == 0:
            continue

        realm = entry.custom['server'].text.encode('utf-8','ignore')
        if realm != 'Aerie Peak':
            toon += '/%s' % realm
        else:
            toon += '/aerie-peak'

        toons.append(toon)

    toons = sorted(toons)

    t5 = time.time()

    # Check if this group already exists in the datastore.  We don't
    # want to overwrite existing progress data for a group if we don't
    # have to.
    query = ranker.Group.query(ranker.Group.name == g)
    results = query.fetch(1)

    responsetext = ''
    loggroup = ''
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
            responsetext = 'Added new group %s with %d toons<br/>\n' % (g,len(toons))
            loggroup = 'Added'
        else:
            responsetext = 'New group %s only has %d toons and was not included<br/>\n' % (g, len(toons))
            loggroup = 'Skipped'
    else:
        # the group already exists and all we need to do is update the
        # toon list.  all of the other data stays the same.
        existing = results[0]
        existing.toons = toons
        existing.put()
        responsetext = 'Updated existing group %s with %d toons<br/>\n' % (g,len(toons))
        loggroup = 'Updated'

    t6 = time.time()

    logging.info('time spent getting toons for %s: %s' % (g, (t5-t4)))
    logging.info('time spent updating db for %s: %s' % (g, (t6-t5)))

    gc.collect()
    return (loggroup, len(toons), responsetext)

class RosterBuilder(webapp2.RequestHandler):

    def get(self):

        path = os.path.join(os.path.split(__file__)[0],'api-auth.json')
        json_key = json.load(open(path))
        gd_client = gdata.spreadsheet.service.SpreadsheetsService()
        gd_client.email = json_key['email']
        gd_client.password = json_key['password']
        gd_client.ProgrammaticLogin()
        logging.info('logged in, grabbing main sheet')

        # Open the main roster feed
        roster_sheet_key = '1tvpsPzZCFupJkTT1y7RmMkuh5VsjBiiA7FvYruJbTtw'
        feed = gd_client.GetWorksheetsFeed(roster_sheet_key)
      
        t1 = time.time()
        # Grab various columns from the DASHBOARD sheet on the spreadsheet, but
        # ignore any groups that are marked as Disbanded.  This is better than
        # looping back through the data again to remove them.
        logging.info('getting roster sheet')
        dashboard_id = getsheetID(feed, 'DASHBOARD')
        dashboard = gd_client.GetListFeed(roster_sheet_key, dashboard_id)

        groupnames = list()
        for entry in dashboard.entry:
            if entry.custom['teamstatus'].text != 'Disbanded':
                groupnames.append(entry.custom['teamname'].text)

        groups = sorted(groupnames)

        logging.info('num groups: %d' % len(groups))
        t2 = time.time()

        groupcount = 0
        tooncount = 0
        responses = list()

        # Grab the list of groups already in the database.  Loop through and
        # delete any groups that don't exist in the list (it happens...) and
        # any groups that are now marked disbanded.  Groups listed in the
        # history will remain even if they disband.
        query = ranker.Group.query()
        results = query.fetch()
        for res in results:
            if res.name not in groups:
                responses.append(('Removed', 'Removed disbanded or non-existent team from database: %s' % res.name))
                res.key.delete()

        t3 = time.time()

        logging.info('time spent getting list of groups %s' % (t2-t1))
        logging.info('time spent cleaning groups %s' % (t3-t2))

        # use a threadpoolexecutor from concurrent.futures to gather the group
        # rosters in parallel.  due to the memory limits on GAE, we only allow
        # 25 threads at a time.  this comes *really* close to hitting both the
        # limit on page-load time and the limit on memory.
        executor = futures.ThreadPoolExecutor(max_workers=25)

        fs = dict()
        for g in groups:
            fs[executor.submit(worker, g, feed, gd_client, roster_sheet_key)] = g

        for future in futures.as_completed(fs):
            g = fs[future]
            if future.exception() is not None:
                logging.info("%s generated an exception: %s" % (g, future.exception()))
            else:
                returnval = future.result()
                responses.append((returnval[0],returnval[2]))
                if returnval[0] == 'Added' or returnval[0] == 'Updated':
                    groupcount += 1
                    tooncount += returnval[1]
        fs.clear()

        self.response.write('<h3>New Raid Groups</h3>')
        added = sorted([x for x in responses if x[0] == 'Added'], key=lambda tup: tup[1])
        for i in added:
            self.response.write('%s<br/>' % i[1])

        self.response.write('<h3>Updated Raid Groups</h3>')
        updated = sorted([x for x in responses if x[0] == 'Updated'], key=lambda tup: tup[1])
        for i in updated:
            self.response.write('%s<br/>' % i[1])

        self.response.write('<h3>Disbanded/Removed Raid Groups</h3>')
        removed = sorted([x for x in responses if x[0] == 'Removed'], key=lambda tup: tup[1])
        for i in removed:
            self.response.write('%s<br/>' % i[1])

        self.response.write('<h3>Raid groups skipped due to Size</h3>')
        skipped = sorted([x for x in responses if x[0] == 'Skipped'], key=lambda tup: tup[1])
        for i in skipped:
            self.response.write('%s<br/>' % i[1])

        t6 = time.time()
        logging.info('time spent building groups %s' % (t6-t3))

        self.response.write('<br/>')
        self.response.write('Now managing %d groups with %d total toons<br/>' % (groupcount, tooncount))

        self.response.write('</body></html>')
