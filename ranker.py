# -*- coding: utf-8 -*-

#!/usr/bin/env python

import webapp2
import json
import time
import logging
from datetime import datetime

from google.appengine.ext import ndb
from google.appengine.api.memcache import Client
from google.appengine.api import taskqueue
from google.appengine.api import urlfetch
from google.appengine.api import urlfetch_errors

class APIKey(ndb.Model):
    key = ndb.StringProperty(indexed=True,required=True)

class Progression(ndb.Model):
    raidname = ndb.StringProperty(indexed = True, required = True)
    numbosses = ndb.IntegerProperty(default = 0, required = True)
    normal = ndb.IntegerProperty(default = 0, required = True)
    heroic = ndb.IntegerProperty(default = 0, required = True)
    mythic = ndb.IntegerProperty(default = 0, required = True)
    
class Group(ndb.Model):
    name = ndb.StringProperty(indexed=True, required = True)
    # TODO: cache progression data?
    toons = ndb.StringProperty(repeated=True)
    brf = ndb.StructuredProperty(Progression, required = True)
    hm = ndb.StructuredProperty(Progression, required = True)

class APIImporter:

    def load(self, toonlist, data):
        q = APIKey.query()
        apikey = q.fetch()[0].key
        
        # Request all of the toon data from the blizzard API and determine the
        # group's ilvls, armor type counts and token type counts.  subs are not
        # included in the counts, since they're not really part of the main
        # group.
        for toon in toonlist:
            try:
                # TODO: this object can probably be a class instead of another dict
                newdata = dict()
                data.append(newdata)

                url = 'https://us.api.battle.net/wow/character/aerie-peak/%s?fields=progression&locale=en_US&apikey=%s' % (toon, apikey)
                # create the rpc object for the fetch method.  the deadline
                # defaults to 5 seconds, but that seems to be too short for the
                # Blizzard API site sometimes.  setting it to 10 helps a little
                # but it makes page loads a little slower.
                rpc = urlfetch.create_rpc(10)
                rpc.callback = self.create_callback(rpc, toon, newdata)
                urlfetch.make_fetch_call(rpc, url)
                newdata['rpc'] = rpc
                newdata['toon'] = toon

                # The Blizzard API has a limit of 10 calls per second.  Sleep here
                # for a very brief time to avoid hitting that limit.
                time.sleep(0.1)
            except:
                logging.error('Failed to create rpc for %s' % toon)

        # Now that all of the RPC calls have been created, loop through the data
        # dictionary one more time and wait for each fetch to be completed. Once
        # all of the waits finish, then we have all of the data from the
        # Blizzard API and can loop through all of it and build the page.
        start = time.time()
        for d in data:
            try:
                d['rpc'].wait()
            except:
                logging.error('Waiting for rpc failed')
        end = time.time()
        
        logging.info("Time spent retrieving data: %f seconds" % (end-start))

    # Callback that handles the result of the call to the Blizzard API.  This will fill in
    # the toondata dict for the requested toon with either data from Battle.net or with an
    # error message to display on the page.
    def handle_result(self, rpc, name, toondata):

        try:
            response = rpc.get_result()
        except urlfetch_errors.DeadlineExceededError:
            logging.error('urlfetch threw DeadlineExceededError on toon %s' % name.encode('ascii','ignore'))
            toondata['toon'] = name
            toondata['status'] = 'nok'
            toondata['reason'] = 'Timeout retrieving data from Battle.net for %s.  Refresh page to try again.' % name
            return
        except urlfetch_errors.DownloadError:
            logging.error('urlfetch threw DownloadError on toon %s' % name.encode('ascii','ignore'))
            toondata['toon'] = name
            toondata['status'] = 'nok'
            toondata['reason'] = 'Network error retrieving data from Battle.net for toon %s.  Refresh page to try again.' % name
            return
        except:
            logging.error('urlfetch threw unknown exception on toon %s' % name.encode('ascii','ignore'))
            toondata['toon'] = name
            toondata['status'] = 'nok'
            toondata['reason'] = 'Unknown error retrieving data from Battle.net for toon %s.  Refresh page to try again.' % name
            return

        # change the json from the response into a dict of data and store it
        # into the toondata object that was passed in.
        jsondata = json.loads(response.content)
        toondata.update(jsondata);

        # Blizzard's API will return an error if it couldn't retrieve the data
        # for some reason.  Check for this and log it if it fails.  Note that
        # this response doesn't contain the toon's name so it has to be added
        # in afterwards.
        if 'status' in jsondata and jsondata['status'] == 'nok':
            logging.error('Blizzard API failed to find toon %s for reason: %s' %
                  (name.encode('ascii','ignore'), jsondata['reason']))
            toondata['toon'] = name
            toondata['reason'] = "Error retrieving data for %s from Blizzard API: %s" % (name, jsondata['reason'])
            return

        # we get all of the data here, but we want to filter out just the raids
        # we care about so that it's not so much data returned from the importer
        validraids = ['Highmaul','Blackrock Foundry']
        if toondata['progression'] != None:
            toondata['progression']['raids'] = [r for r in toondata['progression']['raids'] if r['name'] in validraids]

        del toondata['rpc']

    def create_callback(self, rpc, name, toondata):
        return lambda: self.handle_result(rpc, name, toondata)

class ProgressBuilder(webapp2.RequestHandler):

    def post(self):
        start = self.request.get('start')
        end = self.request.get('end')
        logging.info('%s %s' % (start,end))

        importer = APIImporter()

        q = Group.query()
        groups = q.fetch()

        logging.info('Builder task for range %s to %s started' % (start, end))
        
        for group in groups:
            firstchar = group.name[0]
            if firstchar < start or firstchar > end:
                continue
                
            data = list()
            importer.load(group.toons, data)
            
            progress = dict()
            self.parse(Ranker.difficulties, Ranker.hmbosses, data,
                         'Highmaul', progress)
            self.parse(Ranker.difficulties, Ranker.brfbosses, data,
                         'Blackrock Foundry', progress)
            
            self.response.write(group.name + " data generated<br/>")
            
            # update the entry in ndb with the new progression data for this
            # group.  this also checks to make sure that the progress only ever
            # increases, in case of wierdness with the data.
            group.brf.normal = max(group.brf.normal,
                                   progress['Blackrock Foundry']['normal'])
            group.brf.heroic = max(group.brf.heroic,
                                   progress['Blackrock Foundry']['heroic'])
            group.brf.mythic = max(group.brf.mythic,
                                   progress['Blackrock Foundry']['mythic'])

            group.hm.normal = max(group.hm.normal,
                                  progress['Highmaul']['normal'])
            group.hm.heroic = max(group.hm.heroic,
                                  progress['Highmaul']['heroic'])
            group.hm.mythic = max(group.hm.mythic,
                                  progress['Highmaul']['mythic'])
            
            group.put()
            logging.info('Finished building group %s' % group.name)
        logging.info('Builder task for range %s to %s completed' % (start, end))

    def parse(self, difficulties, bosses, toondata, raidname, progress):

        progress[raidname] = dict()

        bossdata = dict()
        for boss in bosses:
            bossdata[boss] = dict()
            for d in difficulties:
                bossdata[boss][d] = dict()
                bossdata[boss][d]['times'] = list()
                bossdata[boss][d]['timeset'] = set()
                bossdata[boss][d]['killed'] = True
                bossdata[boss][d]['killtime'] = 0
                bossdata[boss][d]['killinv'] = 0

        # loop through each toon in the data from the blizzard API
        for toon in toondata:

            if 'progression' not in toon:
                continue

            # get just the raid data for this toon
            raids = toon['progression']['raids']

            # this filters the raid data down to just the raid we're looking
            # at this pass
            raid = [d for d in raids if d['name'] == raidname][0]

            # loop through the individual bosses and get the timestamp for
            # the last kill for this toon for each boss
            for boss in bosses:
            
                # this filters the raid data down to just a single boss
                b = [d for d in raid['bosses'] if d['name'] == boss][0]

                # loop through each difficulty level and grab each timestamp.
                # skip any timestamps of zero.  that means the toon never
                # killed the boss.
                for d in difficulties:
                    if b[d+'Timestamp'] != 0:
                        bossdata[boss][d]['times'].append(b[d+'Timestamp'])
                        bossdata[boss][d]['timeset'].add(b[d+'Timestamp'])

        # loop back through the difficulties and bosses and build up the
        # progress data
        for d in difficulties:
        
            progress[raidname][d] = 0
            for boss in bosses:

                # for each boss, grab the set of unique timestamps and sort it
                # with the last kill first
                timelist = list(bossdata[boss][d]['timeset'])
                timelist.sort(reverse=True)

                # now loop through that time list.  a kill involving 5 or more
                # players from the group is considered a kill for the whole
                # group and counts towards progress.
                for t in timelist:

                    count = bossdata[boss][d]['times'].count(t)
                    if count >= 5:
                        bossdata[boss][d]['killed'] = True
                        bossdata[boss][d]['killtime'] = t
                        bossdata[boss][d]['killinv'] = count
                        progress[raidname][d] += 1
                        ts = datetime.fromtimestamp(t/1000)
#                    logging.info('count for %s %s at time %s (involved %d members)' % (boss, d, ts.strftime("%Y-%m-%d %H:%M:%S"), count))
                        break
        
class Ranker(webapp2.RequestHandler):

    difficulties = ['normal','heroic','mythic']
    hmbosses = ['Kargath Bladefist','The Butcher','Brackenspore','Twin Ogron','Ko\'ragh','Imperator Mar\'gok']
    brfbosses = ['Oregorger','Gruul','The Blast Furnace','Hans\'gar and Franzok','Flamebender Ka\'graz','Kromog','Beastlord Darmac','Operator Thogar','The Iron Maidens','Blackhand']
            
    def get(self):
        self.response.write("Starting progress tasks")
        taskqueue.add(url='/builder', params={'start':'A', 'end':'B'})
        taskqueue.add(url='/builder', params={'start':'C', 'end':'E'})
        taskqueue.add(url='/builder', params={'start':'F', 'end':'G'})
        taskqueue.add(url='/builder', params={'start':'H', 'end':'H'})
        taskqueue.add(url='/builder', params={'start':'I', 'end':'M'})
        taskqueue.add(url='/builder', params={'start':'N', 'end':'O'})
        taskqueue.add(url='/builder', params={'start':'P', 'end':'R'})
        taskqueue.add(url='/builder', params={'start':'S', 'end':'S'})
        taskqueue.add(url='/builder', params={'start':'T', 'end':'T'})
        taskqueue.add(url='/builder', params={'start':'U', 'end':'Z'})

class Display(webapp2.RequestHandler):
    def get(self):
        # get the group data from the datastore, and order it in decreasing order
        # so that further progressed teams show up first.  break ties by
        # alphabetical order of group names
        q = Group.query().order(-Group.brf.mythic, -Group.brf.heroic, -Group.brf.normal).order(-Group.hm.mythic, -Group.hm.heroic, -Group.hm.normal).order(Group.name)

        groups = q.fetch()
        for group in groups:
            self.response.write("%s<br/>" % group.name)
            self.writeProgress(group.brf)
            self.writeProgress(group.hm)
            self.response.write("<br/>")
            
    def writeProgress(self, raid):
        self.response.write("%s: %d/%dN %d/%dH %d/%dM<br/>" %
                        (raid.raidname, raid.normal, raid.numbosses,
                         raid.heroic, raid.numbosses, raid.mythic,
                         raid.numbosses))
