# -*- coding: utf-8 -*-

#!/usr/bin/env python

import webapp2,jinja2,os
import logging
import wowapi

from datetime import datetime
from google.appengine.ext import ndb
from google.appengine.api.memcache import Client
from google.appengine.api import taskqueue
from google.appengine.api.taskqueue import Queue
from google.appengine.api.taskqueue import QueueStatistics

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'])

class Progression(ndb.Model):
    raidname = ndb.StringProperty(indexed = True, required = True)
    numbosses = ndb.IntegerProperty(default = 0, required = True)
    normal = ndb.IntegerProperty(default = 0, required = True)
    heroic = ndb.IntegerProperty(default = 0, required = True)
    mythic = ndb.IntegerProperty(default = 0, required = True)

class Group(ndb.Model):
    name = ndb.StringProperty(indexed=True, required = True)
    toons = ndb.StringProperty(repeated=True)
    brf = ndb.StructuredProperty(Progression, required = True)
    hm = ndb.StructuredProperty(Progression, required = True)
    lastupdated = ndb.DateTimeProperty(auto_now=True)
    avgilvl = ndb.IntegerProperty(default = 0)

class Global(ndb.Model):
    lastupdated = ndb.DateTimeProperty(auto_now=True)

class ProgressBuilder(webapp2.RequestHandler):

    difficulties = ['normal','heroic','mythic']
    hmbosses = ['Kargath Bladefist','The Butcher','Brackenspore','Twin Ogron','Ko\'ragh','Imperator Mar\'gok']
    brfbosses = ['Oregorger','Gruul','The Blast Furnace','Hans\'gar and Franzok','Flamebender Ka\'graz','Kromog','Beastlord Darmac','Operator Thogar','The Iron Maidens','Blackhand']

    def post(self):
        start = self.request.get('start')
        end = self.request.get('end')
        logging.info('%s %s' % (start,end))

        importer = wowapi.Importer()

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
            self.parse(ProgressBuilder.difficulties, ProgressBuilder.hmbosses,
                       data, 'Highmaul', progress)
            self.parse(ProgressBuilder.difficulties, ProgressBuilder.brfbosses,
                       data, 'Blackrock Foundry', progress)

            # calculate the avg ilvl values from the toon data
            group.avgilvl = 0
            numtoons = 0
            for toon in data:
                if 'items' in toon:
                    numtoons += 1
                    group.avgilvl += toon['items']['averageItemLevel']

            if numtoons != 0:
                group.avgilvl /= numtoons

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

        # update the last updated for the whole dataset.  don't actually
        # have to set the time here, the auto_now flag on the property does
        # it for us.
        q = Global.query()
        r = q.fetch()
        if (len(r) == 0):
            g = Global()
        else:
            g = r[0]
        g.put()

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

    def get(self):
        queue = Queue()
        stats = queue.fetch_statistics()

        template_values={
            'tasks': stats.tasks,
            'in_flight': stats.in_flight,
        }
        template = JINJA_ENVIRONMENT.get_template('templates/ranker.html')
        self.response.write(template.render(template_values))

    def post(self):
        # refuse to start the tasks if there are some already running
        queue = Queue()
        stats = queue.fetch_statistics()
        if stats.tasks == 0:
            print 'nop'
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

        self.redirect('/rank')
        

class Display(webapp2.RequestHandler):
    def get(self):

        q = Global.query()
        r = q.fetch()
        if (len(r)):
            print r[0]

        template_values = {
            'last_updated': r[0].lastupdated
        }
        template = JINJA_ENVIRONMENT.get_template('templates/header.html')
        self.response.write(template.render(template_values))

        # get the group data from the datastore, and order it in decreasing order
        # so that further progressed teams show up first.  break ties by
        # alphabetical order of group names
        q = Group.query().order(-Group.brf.mythic, -Group.brf.heroic, -Group.brf.normal).order(-Group.hm.mythic, -Group.hm.heroic, -Group.hm.normal).order(Group.name)

        groups = q.fetch()
        for group in groups:
            self.response.write('%s (Avg ilvl: %d)<br/>' % (group.name,group.avgilvl))
            self.writeProgress(group.brf)
            self.writeProgress(group.hm)
            self.response.write('<br/>')
        self.response.write('</body></html>')

    def writeProgress(self, raid):
        self.response.write("%s: %d/%dN %d/%dH %d/%dM<br/>" %
                        (raid.raidname, raid.normal, raid.numbosses,
                         raid.heroic, raid.numbosses, raid.mythic,
                         raid.numbosses))
