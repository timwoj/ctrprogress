# -*- coding: utf-8 -*-
#!/usr/bin/env python
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
import json
import logging
import datetime
import time

from pytz.gae import pytz
from google.appengine.api import urlfetch_errors
from google.appengine.api import urlfetch

from ctrpmodels import Boss
from ctrpmodels import Constants
from ctrpmodels import Group
from ctrpmodels import Raid

# Force the deadline for urlfetch to be 10 seconds (Default is 5).  For some
# reason, that first lookup for the spreadsheet takes a bit.
urlfetch.set_default_fetch_deadline(20)

def load_groups():

    time1 = time.time()
    logging.info('retrieving roster data from Raid Builder')
    url = 'http://guild.converttoraid.com/api/teams'
    try:
        response = urlfetch.fetch(url)
    except urlfetch_errors.DeadlineExceededError:
        logging.error('urlfetch threw DeadlineExceededError')
    except urlfetch_errors.DownloadError:
        logging.error('urlfetch threw DownloadError')
    except:
        logging.error('urlfetch threw unknown exception')

    jsondata = json.loads(response.content)

    groupcount = 0
    tooncount = 0
    responses = list()

    time2 = time.time()

    response = '<html><head><title>Roster Update</title></head><body>'

    # Grab the list of groups already in the database.  Loop through and
    # delete any groups that don't exist in the list (it happens...) and
    # any groups that are now marked disbanded. Groups listed in the
    # history will remain even if they disband. While we're looping, also
    # remove any groups from the list to be processed that haven't had
    # a roster update since the last time we did this.
    query = Group.query().order(Group.name)
    results = query.fetch()
    for res in results:

        # Check for groups that don't exist in the jsondata anymore. These
        # groups were removed for whatever reason and should be deleted
        # from the database.
        if res.name not in jsondata:
            responses.append(('Removed', 'Removed disbanded or non-existent team from database: %s' % res.name))
            res.key.delete()
            continue

        # Check for groups that are in both the jsondata and database, but
        # are marked as disbanded in the json data. These should be removed
        # from the database and removed from the json data so they don't
        # get processed later.
        elif jsondata[res.name]['status'] == 'Disbanded':
            responses.append(('Removed', 'Removed team marked disbanded from database: %s' % res.name))
            res.key.delete()

        # if the last updated time exists in the roster data (maccus added
        # it), while we're looping through the groups, also remove any
        # groups from the list to be processed that haven't had a roster
        # update since the last time we parsed groups.
        elif 'updated_at' in jsondata[res.name]:
            # date comes to us as date/time with a timezone. adjust the date time
            # to add the timezone information, then pull just the date out of it
            # in UTC time.
            updated_at = jsondata[res.name]['updated_at']
            updatetime = datetime.datetime.strptime(updated_at['date'], '%Y-%m-%d %H:%M:%S.%f')
            timezone = updated_at['timezone'].replace('\\', '')
            localtime = pytz.timezone(timezone).localize(updatetime)
            lastupdate = localtime.astimezone(pytz.timezone('UTC')).date()

            if res.rosterupdated != None and res.rosterupdated > lastupdate:
                responses.append(('DateUnchanged', '%s hasn\'t been updated since last load (load: %s, update: %s)' % (res.name, res.rosterupdated, lastupdate)))
                groupcount += 1
                tooncount += len(res.toons)
                del jsondata[res.name]

    logging.info('num groups to process: %d', len(jsondata))

    time3 = time.time()

    logging.info('time spent getting list of groups %s', (time2-time1))
    logging.info('time spent cleaning groups %s', (time3-time2))

    # loop through the remaining groups in the json data and process them
    # in one pass.  we don't have to worry about hitting memory limits or
    # anything anymore since we're not making calls into the spreadsheet.
    for group in jsondata:
        if jsondata[group]['status'] == 'Disbanded':
            continue

        returnval = worker(group, jsondata[group])
        responses.append((returnval[0], returnval[2]))
        if returnval[0] == 'Added' or returnval[0] == 'Updated':
            groupcount += 1
            tooncount += returnval[1]

    response += '<h3>New Raid Groups</h3>'
    added = sorted([x for x in responses if x[0] == 'Added'], key=lambda tup: tup[1])
    for i in added:
        response += '%s<br/>' % i[1]

    response += '<h3>Updated Raid Groups</h3>'
    updated = sorted([x for x in responses if x[0] == 'Updated'], key=lambda tup: tup[1])
    for i in updated:
        response += '%s<br/>' % i[1]

    response += '<h3>Disbanded/Removed Raid Groups</h3>'
    removed = sorted([x for x in responses if x[0] == 'Removed'], key=lambda tup: tup[1])
    for i in removed:
        response += '%s<br/>' % i[1]

    response += '<h3>Raid groups skipped due to Size</h3>'
    skipped = sorted([x for x in responses if x[0] == 'Skipped'], key=lambda tup: tup[1])
    for i in skipped:
        response += '%s<br/>' % i[1]

    response += '<h3>Raid groups skipped due to Last Update Date</h3>'
    updatedate = sorted([x for x in responses if x[0] == 'DateUnchanged'], key=lambda tup: tup[1])
    for i in updatedate:
        response += '%s<br/>' % i[1]

    time6 = time.time()
    logging.info('time spent building groups %s', (time6-time3))

    response += '<br/>'
    response += 'Now managing %d groups with %d total toons<br/>' % (groupcount, tooncount)
    response += '</body></html>'

    return response, 200

def worker(name, group):
    time4 = time.time()
    logging.info('working on group %s', name)

    # build up a list of toons for the group from the spreadsheet
    toons = list()

    for toon in group.get('toons', []):

        # skip any toons that aren't marked active, since those toons
        # shouldn't be counted as part of the roster for ilvl
        # TODO: revisit this, could this be done as part of the for above?
        if toon['status'] != 'Active':
            continue

        toons.append('%s/%s' % (toon['toon_name'], toon['realm']))

    toons = sorted(toons)
    time5 = time.time()

    # Check if this group already exists in the datastore.  We don't
    # want to overwrite existing progress data for a group if we don't
    # have to.
    query = Group.query(Group.name == name)
    results = query.fetch(1)

    response = ''
    loggroup = ''
    if not results:
        # create a new group, but only if it has at least 5 toons in
        # it.  that's the threshold for building progress data and
        # there's no real reason to create groups with only that many
        # toons.
        if len(toons) >= 5:
            newgroup = Group(name=name)
            newgroup.bod = Raid()
            newgroup.bod.bosses = list()
            for boss in Constants.bodbosses:
                newboss = Boss(name=boss)
                newgroup.bod.bosses.append(newboss)

            newgroup.toons = toons
            newgroup.rosterupdated = datetime.date.today()

            newgroup.put()
            response = 'Added group %s with %d toons' % (name, len(toons))
            loggroup = 'Added'
        else:
            response = 'New group %s only has %d toons and was not included' % (name, len(toons))
            loggroup = 'Skipped'
    else:
        # the group already exists and all we need to do is update the
        # toon list.  all of the other data stays the same.
        existing = results[0]
        existing.toons = toons
        existing.rosterupdated = datetime.date.today()
        existing.put()
        response = 'Updated group %s with %d toons' % (name, len(toons))
        loggroup = 'Updated'

    time6 = time.time()

    logging.info('time spent getting toons for %s: %s', name, (time5-time4))
    logging.info('time spent updating db for %s: %s', name, (time6-time5))

    return (loggroup, len(toons), response)
