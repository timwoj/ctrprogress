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

            self.processGroup(group, True)

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

    def processGroup(self, group, importer, writeDB):
        logging.info('Starting work on group %s' % group.name)

        data = list()
        importer.load(group.toons, data)

        progress = dict()
        self.parse(Constants.difficulties, Constants.hmbosses,
                   data, Constants.hmname, progress, writeDB)
        self.parse(Constants.difficulties, Constants.brfbosses,
                   data, Constants.brfname, progress, writeDB)

        print progress

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
        # increases, in case of wierdness with the data.  also generate
        # history data while we're at it.
        new_hist = ctrpmodels.HistoryEntry(group=group.name)
        history_changed = False

        # This entire if statement feels like a big hack, with all of the getattr
        # and setattr calls.  It's probably just a fact of how the data models are
        # laid out, but it feels really messy.
        for raid in [('brf',Constants.brfname,Constants.brfbosses),
                     ('hm',Constants.hmname,Constants.hmbosses)]:
            for diff in Constants.difficulties:
                raid_elem = getattr(group, raid[0])
                old_value = getattr(raid_elem, diff)
                new_value = progress[raid[1]][diff]['count']

                if (old_value < new_value):
                    history_changed = True
                    setattr(new_hist, raid[0]+'_'+diff, new_value-old_value)
                    setattr(new_hist, raid[0]+'_'+diff+'_total', new_value)
                    setattr(raid_elem, diff, new_value)

                if raid[0] == 'hm':
                    continue    
                    
                for bossname in raid[2]:
                    if progress[raid[1]][diff][bossname] == True:
                        boss_entry = [b for b in raid_elem.bosses if b.name == bossname][0]
                        setattr(boss_entry, diff+'dead', True)
                    
        print group
                    
        if writeDB:
            group.put()

        if history_changed:
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
            print h
            if writeDB:
                h.put()
        
        logging.info('Finished building group %s' % group.name)

    def parse(self, difficulties, bosses, toondata, raidname, progress, writeDB):

        progress[raidname] = dict()

        bossdata = dict()
        for boss in bosses:
            bossdata[boss] = dict()
            for d in difficulties:
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
                for d in difficulties:
                    if b[d+'Timestamp'] != 0:
                        bossdata[boss][d]['times'].append(b[d+'Timestamp'])
                        bossdata[boss][d]['timeset'].add(b[d+'Timestamp'])

        # loop back through the difficulties and bosses and build up the
        # progress data
        for d in difficulties:

            progress[raidname][d] = dict()
            progress[raidname][d]['count'] = 0
            for boss in bosses:

                progress[raidname][d][boss] = False
                # for each boss, grab the set of unique timestamps and sort it
                # with the last kill first
                timelist = list(bossdata[boss][d]['timeset'])
                timelist.sort(reverse=True)
                print("kill times for %s %s: %s" % (d, boss, str(timelist)))

                # now loop through that time list.  a kill involving 5 or more
                # players from the group is considered a kill for the whole
                # group and counts towards progress.
                for t in timelist:

                    count = bossdata[boss][d]['times'].count(t)
                    print('%s: time: %d   count: %s' % (boss, t, count))
                    if count >= 5:
                        print('*** found valid kill for %s %s at %d' % (d, boss, t))
                        progress[raidname][d]['count'] += 1
                        progress[raidname][d][boss] = True
                        ts = datetime.datetime.fromtimestamp(t/1000)
                        break
                    
    def get(self):
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
        q = History.query(History.date < twoweeksago)
        for r in q.fetch():
            r.key.delete()

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

class Test(webapp2.RequestHandler):
    def get(self):
        importer = wowapi.Importer()

        q = Group.query(Group.name == 'Raided-X')
        groups = q.fetch()

        if len(groups) != 0:
            print group.toons

            data = list()
            importer.load(group.toons, data)

            progress = dict()
            rank = ProgressBuilder()
            rank.parse(Constants.difficulties, Constants.hmbosses,
                       data, 'Highmaul', progress)
            rank.parse(Constants.difficulties, Constants.brfbosses,
                       data, 'Blackrock Foundry', progress)
            print "Finished parsing data"

            print progress
