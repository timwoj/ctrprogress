# -*- coding: utf-8 -*-

#!/usr/bin/env python

import webapp2,jinja2,os,datetime
import logging
import wowapi

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

class HistoryEntry(ndb.Model):
    group = ndb.StringProperty(required = True)
    brf_mythic = ndb.IntegerProperty(default = 0, required = True)
    brf_heroic = ndb.IntegerProperty(default = 0, required = True)
    brf_normal = ndb.IntegerProperty(default = 0, required = True)
    hm_mythic = ndb.IntegerProperty(default = 0, required = True)
    hm_heroic = ndb.IntegerProperty(default = 0, required = True)
    hm_normal = ndb.IntegerProperty(default = 0, required = True)

class History(ndb.Model):
    date = ndb.DateProperty(indexed=True)
    updates = ndb.StructuredProperty(HistoryEntry, repeated = True)

class ProgressBuilder(webapp2.RequestHandler):

    difficulties = ['normal','heroic','mythic']
    hmbosses = ['Kargath Bladefist','The Butcher','Brackenspore','Tectus','Twin Ogron','Ko\'ragh','Imperator Mar\'gok']
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
            # increases, in case of wierdness with the data.  also generate
            # history data while we're at it.
            new_hist = HistoryEntry(group=group.name)
            history_changed = False

            for raid in [['brf','Blackrock Foundry'],['hm','Highmaul']]:
                for diff in ProgressBuilder.difficulties:
                    raid_elem = getattr(group, raid[0])
                    old_value = getattr(raid_elem, diff)
                    new_value = progress[raid[1]][diff]

                    if (old_value < new_value):
                        history_changed = True
                        setattr(new_hist, raid[0]+'_'+diff, new_value)
                        setattr(raid_elem, diff, new_value)

            group.put()

            if history_changed:
                now = datetime.date.today()
                q = History.query(History.date == now)
                r = q.fetch()
                if len(r) != 0:
                    h = r[0]
                else:
                    h = History()
                    h.date = now
                    h.updates = list()
                h.updates.append(new_hist)
                h.put()

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
                logging.debug("%s %s" % (boss, str(timelist)))

                # now loop through that time list.  a kill involving 5 or more
                # players from the group is considered a kill for the whole
                # group and counts towards progress.
                for t in timelist:

                    count = bossdata[boss][d]['times'].count(t)
                    logging.debug('%s: %s' % (boss, count))
                    if count >= 5:
                        bossdata[boss][d]['killed'] = True
                        bossdata[boss][d]['killtime'] = t
                        bossdata[boss][d]['killinv'] = count
                        progress[raidname][d] += 1
                        ts = datetime.datetime.fromtimestamp(t/1000)
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

class Display(webapp2.RequestHandler):
    def get(self):

        q = Global.query()
        r = q.fetch()
        template_values = {
            'last_updated': r[0].lastupdated,
            'title' : 'Main'
        }
        template = JINJA_ENVIRONMENT.get_template('templates/header.html')
        self.response.write(template.render(template_values))

        # get the group data from the datastore, and order it in decreasing order
        # so that further progressed teams show up first.  break ties by
        # alphabetical order of group names
        q = Group.query().order(-Group.brf.mythic, -Group.brf.heroic, -Group.hm.mythic, -Group.brf.normal, -Group.hm.heroic, -Group.hm.normal).order(Group.name)

        groups = q.fetch()
        for group in groups:
            template_values = {'group' : group}
            template = JINJA_ENVIRONMENT.get_template('templates/group.html')
            self.response.write(template.render(template_values))

        self.response.write("</div>")
        self.response.write("<div style='clear: both;font-size: 14px;text-align:center'>Site code by Tamen - Aerie Peak(US) &#149; <a href='http://github.com/timwoj/ctrprogress'>http://github.com/timwoj/ctrprogress<a/></div><br/>")
        self.response.write("<div style='font-size:14px;text-align:center'>This is a community project from the Threat Level Midnight raid group in the Convert to Raid family of guilds - Aerie Peak(US) and is not directly affiliated with the Convert to Raid podcast or Signals Media.</div>")
        self.response.write('</body></html>')

class DisplayText(webapp2.RequestHandler):
    def get(self):

        q = Global.query()
        r = q.fetch()

        template_values = {
            'last_updated': r[0].lastupdated,
            'title' : 'Text Display'
        }
        template = JINJA_ENVIRONMENT.get_template('templates/header.html')
        self.response.write(template.render(template_values))

        # get the group data from the datastore, and order it in decreasing order
        # so that further progressed teams show up first.  break ties by
        # alphabetical order of group names
        q = Group.query().order(-Group.brf.mythic, -Group.brf.heroic, -Group.hm.mythic, -Group.brf.normal, -Group.hm.heroic, -Group.hm.normal).order(Group.name)

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

class DisplayHistory(webapp2.RequestHandler):
    def get(self):
        q = Global.query()
        r = q.fetch()

        template_values = {
            'last_updated': r[0].lastupdated,
            'title' : 'History'
        }
        template = JINJA_ENVIRONMENT.get_template('templates/header.html')
        self.response.write(template.render(template_values))

        # add the beginnings of the table
        self.response.write('<table>')

        # request all of the history entries, sorted in reverse order by date
        r = q.fetch()
        curdate = datetime.date.today()
        oneday = datetime.timedelta(1)

        for i in range(0,13):
            self.response.write('<thead><tr>\n')
            self.response.write('<th colspan="2" style="padding-top:20px">'+str(curdate)+'</th>\n')
            self.response.write('</tr></thead>\n')
            q = History.query(History.date == curdate)
            r = q.fetch()
            if (len(r) == 0):
                # if there were no results for this date, add just a simple
                # entry displaying nothing
                self.response.write('<tr>\n')
                self.response.write('<td colspan="2" style="text-align:center">No history data for this day</td>\n')
                self.response.write('</tr>\n')
            else:
                # if there were results, grab the entries for the day and sort
                # them by group name
                updates = r[0].updates
                updates = sorted(updates, key=lambda k: k.group)

                # now loop through the groups and output the updates in some
                # fashion.  sort the updates BRF -> HM, then M -> H -> N
                for u in updates:

                    q2 = Group.query(Group.name == u.group)
                    r2 = q2.fetch()
                    template_values = {
                        'history': u,
                        'group': r2[0],
                    }
                    template = JINJA_ENVIRONMENT.get_template(
                        'templates/history.html')
                    self.response.write(template.render(template_values))

            self.response.write('</tbody>\n')
            curdate -= oneday

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
            rank.parse(ProgressBuilder.difficulties, ProgressBuilder.hmbosses,
                       data, 'Highmaul', progress)
            rank.parse(ProgressBuilder.difficulties, ProgressBuilder.brfbosses,
                       data, 'Blackrock Foundry', progress)
            print "Finished parsing data"

            print progress
