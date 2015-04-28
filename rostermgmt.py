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
        else:
            toon += '/aerie-peak'

        toons.append(toon)

    toons = sorted(toons)

    t5 = time.time()

    # Check if this group already exists in the datastore.  We don't
    # want to overwrite existing progress data for a group if we don't
    # have to.
    query = ctrpmodels.Group.query(ctrpmodels.Group.name == g)
    results = query.fetch(1)

    responsetext = ''
    loggroup = ''
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
            newgroup.rosterupdated = datetime.date.today()
            newgroup.put()
            responsetext = 'Added group %s with %d toons' % (g,len(toons))
            loggroup = 'Added'
        else:
            responsetext = 'New group %s only has %d toons and was not included' % (g, len(toons))
            loggroup = 'Skipped'
    else:
        # the group already exists and all we need to do is update the
        # toon list.  all of the other data stays the same.
        existing = results[0]
        existing.toons = toons
        existing.rosterupdated = datetime.date.today()
        existing.put()
        responsetext = 'Updated group %s with %d toons' % (g,len(toons))
        loggroup = 'Updated'

    t6 = time.time()

    logging.info('time spent getting toons for %s: %s' % (g, (t5-t4)))
    logging.info('time spent updating db for %s: %s' % (g, (t6-t5)))

    gc.collect()
    return (loggroup, len(toons), responsetext)

class RosterBuilder(webapp2.RequestHandler):

    def get(self):

        self.response.write('<html><head><title>Roster Update</title></head><body>')
        
        path = os.path.join(os.path.split(__file__)[0],'api-auth.json')
        json_key = json.load(open(path))
        gc = gspread.login(json_key['email'], json_key['password'])
        logging.info('logged in, grabbing main sheet')

        sheet = gc.open_by_key('1tvpsPzZCFupJkTT1y7RmMkuh5VsjBiiA7FvYruJbTtw')

        t1 = time.time()
        logging.info('getting group names from dashboard')

        # Grab various columns from the DASHBOARD sheet on the spreadsheet, but
        # ignore any groups that are marked as Disbanded.  This is better than
        # looping back through the data again to remove them.
        dashboard = sheet.worksheet('DASHBOARD')
        dashboard_data = dashboard.get_all_values()
        groupnames = [row[3] for row in dashboard_data if row[3] != '' and row[8] != 'Disbanded']
        lastupdates = [row[10] for row in dashboard_data if row[10] != '' and row[8] != 'Disbanded']

        # delete the first row from all of those lists because it's the header
        # row and it's meaningless
        del groupnames[0]
        del lastupdates[0]

        # sort the lists by the names in the group list.  This is a slick use
        # of zip.
        groupnames, lastupdates = (list(t) for t in zip(*sorted(zip(groupnames,lastupdates))))

        print groupnames
        print lastupdates

        print('num groups on dashboard: %d' % len(groupnames))

        t2 = time.time()

        groupcount = 0
        tooncount = 0
        responses = list()

        # Grab the list of groups already in the database.  Loop through and
        # delete any groups that don't exist in the list (it happens...) and
        # any groups that are now marked disbanded.  Groups listed in the
        # history will remain even if they disband.  While we're looping, also
        # remove any groups from the list to be processed that haven't had
        # a roster update since the last time we did this.
        query = ctrpmodels.Group.query().order(ctrpmodels.Group.name)
        results = query.fetch()
        for res in results:
            if res.name not in groupnames:
                responses.append(('Removed', 'Removed disbanded or non-existent team from database: %s' % res.name))
                res.key.delete()

            # while we're looping through the groups, also remove any groups
            # from the list to be processed that haven't had a roster update
            # since the last time we parsed groups.
            try:
                index = groupnames.index(res.name)
            except ValueError:
                continue

            lastupdate = datetime.datetime.strptime(lastupdates[index], '%m/%d/%Y').date()
            if res.rosterupdated != None and res.rosterupdated > lastupdate:
                responses.append(('DateUnchanged', '%s hasn\'t been updated since last load (load: %s, update: %s)' % (res.name, res.rosterupdated, lastupdate)))
                groupcount += 1
                tooncount += len(res.toons)
                del groupnames[index]
                del lastupdates[index]

        logging.info('num groups to process: %d' % len(groupnames))

        t3 = time.time()

        logging.info('time spent getting list of groups %s' % (t2-t1))
        logging.info('time spent cleaning groups %s' % (t3-t2))

        # use a threadpoolexecutor from concurrent.futures to gather the group
        # rosters in parallel.  due to the memory limits on GAE, we only allow
        # 25 threads at a time.  this comes *really* close to hitting both the
        # limit on page-load time and the limit on memory.
        executor = futures.ThreadPoolExecutor(max_workers=25)

        fs = dict()
        for g in groupnames:
            fs[executor.submit(worker, g, sheet)] = g

        for future in futures.as_completed(fs):
            g = fs[future]
            if future.exception() is not None:
                logging.info("%s generated an exception: %s" % (g, future.exception()))
            else:
                returnval = future.result()
                responses.append((returnval[0], returnval[2]))
                if returnval[0] == 'Added' or returnval[0] == 'Updated':
                    groupcount += 1
                    tooncount += returnval[1]
        fs.clear()

        print responses

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
        for i in updated:
            self.response.write('%s<br/>' % i[1])

        self.response.write('<h3>Raid groups skipped due to Size</h3>')
        skipped = sorted([x for x in responses if x[0] == 'Skipped'], key=lambda tup: tup[1])
        for i in skipped:
            self.response.write('%s<br/>' % i[1])

        self.response.write('<h3>Raid groups skipped due to Last Update Date</h3>')
        updatedate = sorted([x for x in responses if x[0] == 'DateUnchanged'], key=lambda tup: tup[1])
        for i in updatedate:
            self.response.write('%s<br/>' % i[1])

        t6 = time.time()
        logging.info('time spent building groups %s' % (t6-t3))

        self.response.write('<br/>')
        self.response.write('Now managing %d groups with %d total toons<br/>' % (groupcount, tooncount))

        self.response.write('</body></html>')
