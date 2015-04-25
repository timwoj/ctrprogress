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
import operator
import datetime

import ranker
import ctrpmodels

import time
from concurrent import futures
import gc

# Force the deadline for urlfetch to be 10 seconds (Default is 5).  For some
# reason, that first lookup for the spreadsheet takes a bit.
from google.appengine.api import urlfetch
urlfetch.set_default_fetch_deadline(20);

def worker(g, sheet):
    t4 = time.time()
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

    t5 = time.time()

    # Check if this group already exists in the datastore.  We don't
    # want to overwrite existing progress data for a group if we don't
    # have to.
    query = ctrpmodels.Group.query(ctrpmodels.Group.name == g)
    results = query.fetch(1)

    responsetext = ''
    loggroup = False
    if (len(results) == 0):
        # create a new group, but only if it has at least 5 toons in
        # it.  that's the threshold for building progress data and
        # there's no real reason to create groups with only that many
        # toons.
        if (len(toons) >= 5):
            newgroup = ctrpmodels.Group(name=g)
            newgroup.brf = ctrpmodels.Raid()
            newgroup.hm = ctrpmodels.Raid()
            newgroup.hfc = ctrpmodels.Raid()
            newgroup.toons = toons
            newgroup.rosterupdated = datetime.datetime.now()
            newgroup.put()
            responsetext = 'Added group %s with %d toons' % (g,len(toons))
            loggroup = True
        else:
            responsetext = 'New group %s only has %d toons and was not included<br/>\n' % (g, len(toons))
    else:
        # the group already exists and all we need to do is update the
        # toon list.  all of the other data stays the same.
        existing = results[0]
        existing.toons = toons
        existing.rosterupdated = datetime.datetime.now()
        existing.put()
        responsetext = 'Updated group %s with %d toons<br/>\n' % (g,len(toons))
        loggroup = True

    t6 = time.time()

    logging.info('time spent getting toons for %s: %s' % (g, (t5-t4)))
    logging.info('time spent updating db for %s: %s' % (g, (t6-t5)))

    gc.collect()
    return (loggroup, len(toons), responsetext)

class RosterBuilder(webapp2.RequestHandler):

    def get(self):

        path = os.path.join(os.path.split(__file__)[0],'api-auth.json')
        json_key = json.load(open(path))
        gc = gspread.login(json_key['email'], json_key['password'])
        logging.info('logged in, grabbing main sheet')

        sheet = gc.open_by_key('1tvpsPzZCFupJkTT1y7RmMkuh5VsjBiiA7FvYruJbTtw')

        t1 = time.time()
        logging.info('getting roster sheet')
        bigroster = sheet.worksheet('BIG ROSTER BOARD')
        groupnames = bigroster.row_values(1)
        actives = bigroster.row_values(2)
        groups = list()

        # Grab all of the group names, but discard any that are marked
        # Disbanded.  This will cause disbanded groups to get deleted in the
        # next part.
        for i,group in enumerate(groupnames):
            if len(group) > 0 and actives[i] != 'Disbanded':
                groups.append(group)
        groups = sorted(groups)
        
        logging.info('num groups on master roster: %d' % len(groups))
        t2 = time.time()

        # Grab the list of groups already in the database.  Loop through and
        # delete any groups that don't exist in the list (it happens...) and
        # any groups that are now marked disbanded.  Groups listed in the
        # history will remain even if they disband.
        query = ctrpmodels.Group.query()
        results = query.fetch()
        for res in results:
            if res.name not in groups:
                self.response.write('Removed disbanded or non-existent team: %s<br/>\n' % res.name)
                res.key.delete()

        t3 = time.time()

        logging.info('time spent getting list of groups %s' % (t2-t1))
        logging.info('time spent cleaning groups %s' % (t3-t2))

        # use a threadpoolexecutor from concurrent.futures to gather the group
        # rosters in parallel.  due to the memory limits on GAE, we only allow
        # 25 threads at a time.  this comes *really* close to hitting both the
        # limit on page-load time and the limit on memory.
        groupcount = 0
        tooncount = 0
        responses = dict()

        executor = futures.ThreadPoolExecutor(max_workers=25)

        fs = dict()
        for g in groups:
            fs[executor.submit(worker, g, sheet)] = g

        for future in futures.as_completed(fs):
            g = fs[future]
            if future.exception() is not None:
                logging.info("%s generated an exception: %s" % (g, future.exception()))
            else:
                returnval = future.result()
                responses[g] = returnval[2]
                if returnval[0] == True:
                    groupcount += 1
                    tooncount += returnval[1]
        fs.clear()

        responses = sorted(responses.items(), key=operator.itemgetter(0))
        for i in responses:
            self.response.write(i[1])

        t6 = time.time()
        logging.info('time spent building groups %s' % (t6-t3))

        self.response.write('<br/>')
        self.response.write('Now managing %d groups with %d total toons<br/>' % (groupcount, tooncount))
