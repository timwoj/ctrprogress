# -*- coding: utf-8 -*-

#!/usr/bin/env python

import webapp2,jinja2,os,datetime
import logging
import wowapi

from ctrpmodels import Constants
from ctrpmodels import Group
import ctrpmodels

from google.appengine.ext import ndb
from google.appengine.api.memcache import Client
from google.appengine.api import taskqueue
from google.appengine.api.taskqueue import Queue
from google.appengine.api.taskqueue import QueueStatistics

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'])

class ProgressBuilder(webapp2.RequestHandler):

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

            self.processGroup(group, importer, True)
            break

        logging.info('Builder task for range %s to %s completed' % (start, end))

        # update the last updated for the whole dataset.  don't actually
        # have to set the time here, the auto_now flag on the property does
        # it for us.
        q = ctrpmodels.Global.query()
        r = q.fetch()
        if (len(r) == 0):
            g = ctrpmodels.Global()
        else:
            g = r[0]
        g.put()

    def processGroup(self, group, importer, writeDB):
        logging.info('Starting work on group %s' % group.name)

        data = list()
        importer.load(group.toons, data)

        progress = dict()
        self.parse(Constants.hmbosses, data, Constants.hmname, progress, writeDB)
        self.parse(Constants.brfbosses, data, Constants.brfname, progress, writeDB)

        # calculate the avg ilvl values from the toon data
        group.avgilvl = 0
        numtoons = 0
        for toon in data:
            # ignore toons that we didn't get data back for or for toons less than
            # level 100
            if 'items' in toon and toon['level'] == 100:
                numtoons += 1
                group.avgilvl += toon['items']['averageItemLevel']

        if numtoons != 0:
            group.avgilvl /= numtoons

        self.response.write(group.name + " data generated<br/>")

        # update the entry in ndb with the new progression data for this
        # group.  this also checks to make sure that the progress only ever
        # increases, in case of weirdness with the data.  also generate
        # history data while we're at it.
        new_hist = None

        # Loop through the raids that are being processed for this tier and
        # build all of the points of data that are needed.  First, update which
        # bosses have been killed for a group, then loop through the
        # difficulties and build the killed counts and the history.
        for raid in [('brf',Constants.brfname,Constants.brfbosses),
                     ('hm',Constants.hmname,Constants.hmbosses)]:

            group_raid = getattr(group, raid[0])
            data_raid = progress[raid[1]]

            for group_boss in group_raid.bosses:
                data_boss = [b for b in data_raid if b.name == group_boss.name][0]
                if data_boss.normaldead == True:
                    group_boss.normaldead = True
                if data_boss.heroicdead == True:
                    group_boss.heroicdead = True
                if data_boss.mythicdead == True:
                    group_boss.mythicdead = True

            for d in Constants.difficulties:
                old = getattr(group_raid, d)
                new = len([b for b in group_raid.bosses if getattr(b, d+'dead') == True])
                if old < new:
                    if (new_hist == None):
                        new_hist = ctrpmodels.HistoryEntry(group=group.name)
                    setattr(new_hist, raid[0]+'_'+d, new-old)
                    setattr(new_hist, raid[0]+'_'+d+'_total', new)
                    setattr(group_raid, d, new)

        if writeDB:
            group.put()

        if new_hist != None:
            now = datetime.date.today()
            q = ctrpmodels.History.query(ctrpmodels.History.date == now)
            r = q.fetch()
            if len(r) != 0:
                h = r[0]
            else:
                h = ctrpmodels.History()
                h.date = now
                h.updates = list()
            h.updates.append(new_hist)
            if writeDB:
                h.put()

            h = None
            new_hist = None
        
        logging.info('Finished building group %s' % group.name)

    def parse(self, bosses, toondata, raidname, progress, writeDB):

        progress[raidname] = list()

        bossdata = dict()
        for boss in bosses:
            bossdata[boss] = dict()
            for d in Constants.difficulties:
                bossdata[boss][d] = dict()
                bossdata[boss][d]['times'] = list()
                bossdata[boss][d]['timeset'] = set()

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
                for d in Constants.difficulties:
                    if b[d+'Timestamp'] != 0:
                        bossdata[boss][d]['times'].append(b[d+'Timestamp'])
                        bossdata[boss][d]['timeset'].add(b[d+'Timestamp'])

        # loop back through the difficulties and bosses and build up the
        # progress data
        for boss in bosses:

            bossobj = ctrpmodels.Boss(name = boss)

            for d in Constants.difficulties:
                # for each boss, grab the set of unique timestamps and sort it
                # with the last kill first
                timelist = list(bossdata[boss][d]['timeset'])
                timelist.sort(reverse=True)
                logging.info("kill times for %s %s: %s" % (d, boss, str(timelist)))

                for t in timelist:
                    count = bossdata[boss][d]['times'].count(t)
                    logging.info('%s: time: %d   count: %s' % (boss, t, count))
                    if count >= 5:
                        logging.info('*** found valid kill for %s %s at %d' % (d, boss, t))
                        setattr(bossobj, d+'dead', True)
                        break

            progress[raidname].append(bossobj)
            
    def loadone(self):
        group = self.request.get('group')
        logging.info('loading single %s' % group)
        q = Group.query(Group.name == group)
        groups = q.fetch()
        logging.info('found %d groups with that name' % len(groups))
        if (len(groups) != 0):
            importer = wowapi.Importer()
            self.processGroup(groups[0], importer, False)

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
        # clear out any history older than two weeks
        twoweeksago = datetime.date.today() - datetime.timedelta(14)
        q = ctrpmodels.History.query(ctrpmodels.History.date < twoweeksago)
        for r in q.fetch():
            r.key.delete()

        # refuse to start the tasks if there are some already running
        queue = Queue()
        stats = queue.fetch_statistics()
        if stats.tasks == 0:
            #taskqueue.add(url='/builder', params={'start':'A', 'end':'B'})
            #taskqueue.add(url='/builder', params={'start':'C', 'end':'E'})
            #taskqueue.add(url='/builder', params={'start':'F', 'end':'G'})
            #taskqueue.add(url='/builder', params={'start':'H', 'end':'H'})
            #taskqueue.add(url='/builder', params={'start':'I', 'end':'M'})
            #taskqueue.add(url='/builder', params={'start':'N', 'end':'O'})
            #taskqueue.add(url='/builder', params={'start':'P', 'end':'R'})
            #taskqueue.add(url='/builder', params={'start':'S', 'end':'S'})
            taskqueue.add(url='/builder', params={'start':'T', 'end':'T'})
            #taskqueue.add(url='/builder', params={'start':'U', 'end':'Z'})

        self.redirect('/rank')

class Test(webapp2.RequestHandler):
    def get(self):
        importer = wowapi.Importer()

        q = Group.query(Group.name == 'Raided-X')
        groups = q.fetch()

        if len(groups) != 0:

            data = list()
            importer.load(group.toons, data)

            progress = dict()
            rank = ProgressBuilder()
            rank.parse(Constants.difficulties, Constants.hmbosses,
                       data, 'Highmaul', progress)
            rank.parse(Constants.difficulties, Constants.brfbosses,
                       data, 'Blackrock Foundry', progress)
            logging.info("Finished parsing data")

            logging.info(progress)
